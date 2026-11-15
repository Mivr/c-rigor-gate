"""The evidence PNG writer of `rigor ui-explore` (rigor_lib.ui_explore_png): its output is decoded back with the stdlib
(chunk lengths and CRCs, IHDR, zlib, row filters) by a reader written here, independent of the writer."""

import struct
import unittest
import zlib

from rigor_lib import ui_explore_png as png


def decode(data):
    """(width, height, rgba) of an 8-bit RGBA, non-interlaced PNG; asserts every structural rule on the way."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "signature"
    at, chunks = 8, []
    while at < len(data):
        (length,) = struct.unpack(">I", data[at:at + 4])
        kind, body = data[at + 4:at + 8], data[at + 8:at + 8 + length]
        (crc,) = struct.unpack(">I", data[at + 8 + length:at + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xffffffff, "crc of %r" % kind
        chunks.append((kind, body))
        at += 12 + length
    assert at == len(data), "trailing bytes"
    assert [kind for kind, _ in chunks][0] == b"IHDR" and chunks[-1] == (b"IEND", b""), "chunk order"
    width, height, depth, colour, method, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    assert (depth, colour, method, filtering, interlace) == (8, 6, 0, 0, 0), "header"
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride = width * 4
    assert len(raw) == height * (stride + 1), "size"
    rows, previous = [], bytes(stride)
    for y in range(height):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            left = line[i - 4] if i >= 4 else 0
            up = previous[i]
            if kind == 1:
                line[i] = (line[i] + left) & 0xff
            elif kind == 2:
                line[i] = (line[i] + up) & 0xff
            else:
                assert kind == 0, "filter %d" % kind
        rows.append(bytes(line))
        previous = rows[-1]
    return width, height, b"".join(rows)


class PngTest(unittest.TestCase):
    def test_round_trip(self):
        width, height = 5, 3
        rgba = bytes((x * 37 + y * 11 + c * 5) & 0xff for y in range(height) for x in range(width) for c in range(4))
        data = png.write_png(width, height, rgba)
        self.assertEqual(decode(data), (width, height, rgba))
        self.assertEqual(png.write_png(width, height, rgba), data)

    def test_crop(self):
        width, height = 4, 3
        rgba = bytes(range(width * height * 4))
        part = png.crop(width, height, rgba, (1, 1, 2, 2))
        self.assertEqual(part, rgba[20:28] + rgba[36:44])
        self.assertEqual(decode(png.write_png(2, 2, part)), (2, 2, part))

    def test_refusals(self):
        with self.assertRaises(ValueError):
            png.write_png(2, 2, bytes(15))
        with self.assertRaises(ValueError):
            png.write_png(0, 2, b"")
        with self.assertRaises(ValueError):
            png.write_png(True, 1, bytes(4))
        for box in ((3, 0, 2, 1), (0, 0, 0, 1), (-1, 0, 1, 1), (0, 2, 1, 2)):
            with self.assertRaises(ValueError, msg=box):
                png.crop(4, 3, bytes(48), box)
