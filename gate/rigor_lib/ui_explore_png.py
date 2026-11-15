"""Evidence images for `rigor ui-explore` (P004 4.5): a stdlib PNG writer (`zlib`, `struct`) for 8-bit RGBA, and a
crop of an RGBA frame. Deterministic: the same pixels give the same bytes (fixed compression level, no ancillary chunk,
filter type 0 on every row)."""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SIDE = 1 << 14


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)


def _check(width, height, rgba):
    if type(width) is not int or type(height) is not int or not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError("png: width and height must be integers in 1..%d" % MAX_SIDE)
    if not isinstance(rgba, (bytes, bytearray)) or len(rgba) != width * height * 4:
        raise ValueError("png: want %d bytes of RGBA, got %s" % (width * height * 4, len(rgba)
                                                                  if isinstance(rgba, (bytes, bytearray)) else "none"))


def write_png(width, height, rgba):
    """The PNG file bytes of a `width` x `height` image given as rows of RGBA bytes (top row first)."""
    _check(width, height, rgba)
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(rgba[row * stride:(row + 1) * stride]) for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def crop(width, height, rgba, box):
    """The RGBA bytes of `box` = (x, y, w, h) inside the frame; the box must lie inside it and not be empty."""
    _check(width, height, rgba)
    x, y, w, h = box
    if any(type(v) is not int for v in box) or w < 1 or h < 1 or x < 0 or y < 0 or x + w > width or y + h > height:
        raise ValueError("png: crop box %r is not inside %dx%d" % (box, width, height))
    stride = width * 4
    return b"".join(bytes(rgba[(y + row) * stride + x * 4:(y + row) * stride + (x + w) * 4]) for row in range(h))
