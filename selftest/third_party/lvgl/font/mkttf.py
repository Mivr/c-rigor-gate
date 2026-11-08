#!/usr/bin/env python3
"""Writes selftest/third_party/lvgl/font/box.ttf (T114): a minimal TrueType font made from nothing, Python stdlib only.

Three glyphs besides .notdef: 'A' (a triangle), 'B' (a square) and U+0411 (a square with a notch, a Cyrillic code
point so the font is not Latin-only). Public domain (CC0): geometry invented for this self-test, no third-party font
data. Run: python3 -I -B mkttf.py box.ttf
"""
import struct
import sys

UPM = 1000


def glyph(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    out = struct.pack(">hhhhh", 1, min(xs), min(ys), max(xs), max(ys))
    out += struct.pack(">H", len(points) - 1) + struct.pack(">H", 0)
    out += bytes([1] * len(points))  # on curve, 16 bit deltas
    for axis in (0, 1):
        prev = 0
        for p in points:
            out += struct.pack(">h", p[axis] - prev)
            prev = p[axis]
    return out + b"\0" * (-len(out) % 4)


GLYPHS = [
    glyph([(100, 0), (500, 0), (500, 700), (100, 700)]),                      # .notdef
    glyph([(50, 0), (650, 0), (350, 700)]),                                   # A
    glyph([(100, 0), (600, 0), (600, 700), (100, 700)]),                      # B
    glyph([(100, 0), (600, 0), (600, 700), (350, 400), (100, 700)]),          # U+0411
]
CODES = [(0x41, 0x42, 1), (0x411, 0x411, 3), (0xFFFF, 0xFFFF, 0)]
ADV = 700


def tables():
    glyf = b"".join(GLYPHS)
    offs, pos = [], 0
    for g in GLYPHS:
        offs.append(pos)
        pos += len(g)
    offs.append(pos)
    loca = b"".join(struct.pack(">I", o) for o in offs)
    head = struct.pack(">IIIIHHqqhhhhHHhhh", 0x00010000, 0x00010000, 0, 0x5F0F3CF5, 0, UPM, 0, 0,
                       0, -200, 700, 800, 0, 8, 2, 1, 0)
    hhea = struct.pack(">IhhhHhhhhhhhhhhhH", 0x00010000, 800, -200, 0, ADV, 0, 0, 700, 1, 0, 0, 0, 0, 0, 0, 0,
                       len(GLYPHS))
    hmtx = b"".join(struct.pack(">Hh", ADV, 0) for _ in GLYPHS)
    maxp = struct.pack(">IHHHHHHHHHHHHHH", 0x00010000, len(GLYPHS), 8, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    n = len(CODES)
    seg = struct.pack(">HHHH", n * 2, 4, 1, 2)  # segCountX2, searchRange, entrySelector, rangeShift for 3 segments
    seg += b"".join(struct.pack(">H", c[1]) for c in CODES) + b"\0\0"
    seg += b"".join(struct.pack(">H", c[0]) for c in CODES)
    seg += b"".join(struct.pack(">H", (c[2] - c[0]) & 0xFFFF if c[0] != 0xFFFF else 1) for c in CODES)
    seg += b"\0\0" * n
    sub = struct.pack(">HHH", 4, 6 + len(seg), 0) + seg
    cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + sub
    return {b"cmap": cmap, b"glyf": glyf, b"head": head, b"hhea": hhea, b"hmtx": hmtx, b"loca": loca, b"maxp": maxp}


def checksum(data):
    data += b"\0" * (-len(data) % 4)
    return sum(struct.unpack(">%dI" % (len(data) // 4), data)) & 0xFFFFFFFF


def main(path):
    tabs = tables()
    names = sorted(tabs)
    head = struct.pack(">IHHHH", 0x00010000, len(names), 64, 2, len(names) * 16 - 64)
    offset = 12 + 16 * len(names)
    directory, body = b"", b""
    for name in names:
        data = tabs[name]
        directory += name + struct.pack(">III", checksum(data), offset + len(body), len(data))
        body += data + b"\0" * (-len(data) % 4)
    with open(path, "wb") as f:
        f.write(head + directory + body)


if __name__ == "__main__":
    main(sys.argv[1])
