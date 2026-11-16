"""The ink facts the `ui-render` judge reads (U07, P004 3.3): the `ink` and `noink` records of one state's frame
(docs/ui-lvprobe.md, "Definitions" and "Text format"), and the WCAG contrast of an ink record.

Ink is what lvprobe measures by hiding a node and re-rendering its box: `count` pixels changed; `ink_lo`/`ink_hi` are
the darkest and the lightest of those pixels as drawn WITH the node, `bg_lo`/`bg_hi` the darkest and the lightest of the
same pixels WITHOUT it (what is behind), each chosen by lvprobe's luma `2126 R + 7152 G + 722 B` over the encoded
channels. A pixel a later object overwrites does not change, so it is not ink. `noink unstable` / `noink transformed`
is data: nothing was measured.

The records are gate-written (lvprobe through the probe), so a record that breaks their shape, or an `ink` reply that
does not name every non-root node of the walk exactly once, is the gate's error (InternalError, exit 2).
"""

import re
from dataclasses import dataclass

from rigor_lib.errors import InternalError

_INT = re.compile(r"0|[1-9][0-9]{0,9}")
_BOX = re.compile(r"(-?[0-9]{1,10}),(-?[0-9]{1,10}),(-?[0-9]{1,10}),(-?[0-9]{1,10})")
_HEX6 = re.compile(r"[0-9a-f]{6}")
NOINK_REASONS = ("unstable", "transformed")


def _fail(why):
    raise InternalError("ui-render: the ink facts break their own format: %s" % why)


@dataclass(frozen=True)
class Ink:
    """One `ink` record (measured) or `noink` record (`reason` set, nothing measured)."""
    index: int
    reason: object          # None (measured), "unstable" or "transformed"
    count: int
    box: object
    ink_lo: str
    ink_hi: str
    bg_lo: str
    bg_hi: str
    raw: str


def _int(text, what):
    if not _INT.fullmatch(text):
        _fail("%s %r is not a decimal integer" % (what, text))
    return int(text)


def _record(record):
    f = record.fields
    index = _int(f[1], "ink index")
    if f[0] == "noink":
        if f[2] not in NOINK_REASONS:
            _fail("a noink reason %r" % f[2])
        return Ink(index, f[2], 0, None, "", "", "", "", record.raw)
    count = _int(f[2], "ink count")
    box = None
    if f[3] != "-":
        found = _BOX.fullmatch(f[3])
        if not found:
            _fail("an ink box %r" % f[3])
        box = tuple(int(v) for v in found.groups())
    if (box is None) != (count == 0):
        _fail("an ink box that does not match its count")
    colours = f[4:8]
    if not all(_HEX6.fullmatch(c) for c in colours):
        _fail("an ink colour that is not 6 lowercase hex digits")
    return Ink(index, None, count, box, colours[0], colours[1], colours[2], colours[3], record.raw)


def parse_ink(records, frame):
    """{walk index: Ink} of every non-root node of `frame` (the frame the ink was taken on)."""
    out = {}
    for record in records:
        if record.fields[0] not in ("ink", "noink"):
            _fail("a %s record in an ink reply" % record.fields[0])
        item = _record(record)
        if item.index >= len(frame.nodes) or frame.is_root(item.index) or item.index in out:
            _fail("ink record %d is not one non-root node of the walk" % item.index)
        out[item.index] = item
    wanted = [n.index for n in frame.nodes if not frame.is_root(n.index)]
    if sorted(out) != wanted:
        _fail("an ink reply that does not name every non-root node of the walk")
    return out


# ---- WCAG 2.x relative luminance and contrast ratio -----------------------------------------------------------------
def _linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    """WCAG relative luminance of a 6 hex digit sRGB colour."""
    r, g, b = (int(rgb[k:k + 2], 16) for k in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def ratio(a, b):
    """WCAG contrast ratio of two relative luminances (1 to 21)."""
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def worst_contrast(ink):
    """The contrast a text node's ink gives at the least, against what is behind it (docs/ui-judges-render.md,
    "contrast-low"): the text colour is one of the two ink extremes (antialiased edge pixels are blends of the text
    colour with what is behind, so they never are the text colour; the extreme farther from the background is); the
    background is anywhere in the luminance interval of the two background extremes, so the nearest point of that
    interval is taken (a text colour inside it gives 1:1). Result: max over the two ink extremes of the min over the
    background interval."""
    low, high = sorted((luminance(ink.bg_lo), luminance(ink.bg_hi)))
    best = 1.0
    for text in (luminance(ink.ink_lo), luminance(ink.ink_hi)):
        if low <= text <= high:
            continue
        best = max(best, ratio(text, low if text < low else high))
    return best


def against_fill(ink, fill):
    """The contrast of a text carrier that paints its own exactly opaque, single-colour background `fill`: its ink is
    the fill (which differs from what is behind it) and the glyphs on it, so its two extremes are the fill, the text
    colour or a blend of the two; the text colour is the extreme farther from the fill. Result: max over the two ink
    extremes of their ratio to the fill. An upper bound of the text's contrast (a border, outline or shadow of the
    label, which the facts do not show, could be the farther extreme), so only a value BELOW a threshold is sound."""
    base = luminance(fill)
    return max(ratio(luminance(ink.ink_lo), base), ratio(luminance(ink.ink_hi), base))
