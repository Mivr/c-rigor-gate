"""The rendered tree the ui-scene and ui-fit judges read (U06, P004 2.1 stage O3): the lvprobe records of a step's `frame`
reply (`node`, `label`, `fit`, `frame`; docs/ui-lvprobe.md, "Text format"). They are written by gate code, so a record
that breaks their shape is the gate's error (InternalError, exit 2). The scene (O2) and the association of the two are
ui_judge_vocab.
"""

import re
from dataclasses import dataclass, field

from rigor_lib.errors import InternalError

_INT = re.compile(r"0|-?[1-9][0-9]{0,17}")
_BOX = re.compile(r"(-?[0-9]{1,10}),(-?[0-9]{1,10}),(-?[0-9]{1,10}),(-?[0-9]{1,10})")


def _fail(why):
    raise InternalError("ui judges: the frame facts break their own format: %s" % why)


def _int(text, what):
    if not _INT.fullmatch(text):
        _fail("%s %r is not a decimal integer" % (what, text))
    return int(text)


def _flag(text, what):
    if text not in ("0", "1"):
        _fail("%s %r is not 0 or 1" % (what, text))
    return text == "1"


def _box(text, what):
    if text == "-":
        return None
    found = _BOX.fullmatch(text)
    if not found:
        _fail("%s %r is not a box" % (what, text))
    return tuple(int(v) for v in found.groups())


# ---- O3 -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RNode:
    """One `node` record (docs/ui-lvprobe.md, "Text format"). Boxes are inclusive (x1, y1, x2, y2)."""
    index: int
    parent: int
    depth: int
    cls: str
    box: tuple
    bg: str
    hidden: bool
    clickable: bool
    clip: int
    scroll: int
    bg_opa_drawn: int
    bg_opa_exact: bool
    bg_grad: bool
    bg_image: bool
    raw: str


@dataclass(frozen=True)
class RLabel:
    index: int
    line_h: int
    align: int           # the text-align style (lv_text_align_t: 0 auto, 1 left, 2 centre, 3 right)
    align_drawn: int     # the alignment of the label's draw task (U07)
    long_mode: int
    dotted: bool
    lines: int
    natural: tuple
    laid: tuple
    text: bytes          # what LVGL draws
    own_text: bytes      # the label's own text (`full_text` when dotted)
    raw: str


@dataclass(frozen=True)
class RFit:
    index: int
    drawn: bool
    unsupported: bool
    glyphs: object
    visible: object
    missing: int
    clipped: bool
    raw: str


@dataclass
class Frame:
    width: int
    height: int
    nodes: list
    labels: dict
    fits: dict
    end: list = field(default_factory=list)            # index of the last node of each node's subtree
    children: dict = field(default_factory=dict)

    def is_root(self, index):
        return self.nodes[index].parent == -1

    def descends(self, index, ancestor):
        """index is in the subtree of ancestor (itself included)."""
        return ancestor <= index <= self.end[ancestor]

    def related(self, a, b):
        return self.descends(a, b) or self.descends(b, a)

    def shown(self, index):
        """Not hidden, nor any ancestor."""
        while index != -1:
            if self.nodes[index].hidden:
                return False
            index = self.nodes[index].parent
        return True

    def ancestors(self, index):
        out = []
        index = self.nodes[index].parent
        while index != -1:
            out.append(index)
            index = self.nodes[index].parent
        return out

    def visible_box(self, index):
        """The node's box cut by the display and by the boxes along its clip chain (lvprobe's `clip` ancestor)."""
        box = intersect(self.nodes[index].box, (0, 0, self.width - 1, self.height - 1))
        clip = self.nodes[index].clip
        while box is not None and clip != -1:
            box = intersect(box, self.nodes[clip].box)
            clip = self.nodes[clip].clip
        return box


def intersect(a, b):
    """Inclusive boxes; None when they share no pixel."""
    if a is None or b is None:
        return None
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return box if box[0] <= box[2] and box[1] <= box[3] else None


def inside(inner, outer):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _node(record):
    f = record.fields
    return RNode(index=_int(f[1], "node index"), parent=_int(f[2], "parent"), depth=_int(f[3], "depth"),
                 cls=f[4], box=tuple(_int(f[k], "coordinate") for k in (5, 6, 7, 8)), bg=f[15],
                 hidden=_flag(f[9], "hidden"), clickable=_flag(f[10], "clickable"), clip=_int(f[11], "clip"),
                 scroll=_int(f[12], "scroll"), bg_opa_drawn=_int(f[17], "bg_opa_drawn"),
                 bg_opa_exact=_flag(f[18], "bg_opa_exact"), bg_grad=_flag(f[19], "bg_grad"),
                 bg_image=_flag(f[20], "bg_image"), raw=record.raw)


def _label(record):
    f, v = record.fields, record.values
    if not v[13].startswith(b"=") or not (f[14] == "-" or v[14].startswith(b"=")):
        _fail("a label text without its `=` prefix")
    dotted = _flag(f[7], "dotted")
    if dotted == (f[14] == "-"):
        _fail("a label whose full text does not match its dotted flag")
    text = v[13][1:]
    return RLabel(index=_int(f[1], "label index"), line_h=_int(f[3], "line_h"), align=_int(f[4], "align"),
                  align_drawn=_int(f[5], "align_drawn"), long_mode=_int(f[6], "long"),
                  dotted=dotted, lines=_int(f[8], "lines"), natural=(_int(f[9], "natural_w"), _int(f[10], "natural_h")),
                  laid=(_int(f[11], "laid_w"), _int(f[12], "laid_h")), text=text,
                  own_text=v[14][1:] if dotted else text, raw=record.raw)


def _fit(record):
    f = record.fields
    return RFit(index=_int(f[1], "fit index"), drawn=_flag(f[2], "drawn"), unsupported=_flag(f[3], "unsupported"),
                glyphs=_box(f[4], "glyphs"), visible=_box(f[5], "visible"), missing=_int(f[6], "missing"),
                clipped=_flag(f[7], "clipped"), raw=record.raw)


# The frame-fact records the judges read, and those they ignore (docs/ui-model.md, "Frame facts"): `region` hashes,
# `life` events, and `taps` (the tap path of a session's first frame: entry, indev or probe; U05c).
JUDGED = frozenset(("lvprobe", "frame", "node", "label", "fit"))
IGNORED = frozenset(("region", "life", "taps"))


def parse_frame(records):
    """The O3 facts of one `frame` reply (parsed records with frame-facts). Every shape rule is checked."""
    heads = [r for r in records if r.fields[0] in ("lvprobe", "frame")]
    if [r.fields[0] for r in heads] != ["lvprobe", "frame"]:
        _fail("a frame reply without exactly one lvprobe and one frame record")
    count = _int(heads[0].fields[2], "node count")
    width, height = _int(heads[1].fields[1], "width"), _int(heads[1].fields[2], "height")
    nodes, labels, fits = [], {}, {}
    for record in records:
        kind = record.fields[0]
        if kind not in JUDGED and kind not in IGNORED:
            _fail("a %s record, which the frame facts do not have" % kind)
        if kind == "node":
            node = _node(record)
            if node.index != len(nodes) or not -1 <= node.parent < node.index:
                _fail("node %d out of walk order" % node.index)
            nodes.append(node)
        elif kind in ("label", "fit"):
            item = _label(record) if kind == "label" else _fit(record)
            table = labels if kind == "label" else fits
            if item.index != len(nodes) - 1 or item.index in table or (kind == "fit" and item.index not in labels):
                _fail("a %s record that does not follow its node" % kind)
            table[item.index] = item
    if len(nodes) != count:
        _fail("%d node records, the head says %d" % (len(nodes), count))
    frame = Frame(width, height, nodes, labels, fits)
    _tree(frame)
    return frame


def _tree(frame):
    frame.end = list(range(len(frame.nodes)))
    stack = []
    for node in frame.nodes:
        want = 0 if node.parent == -1 else frame.nodes[node.parent].depth + 1
        if node.depth != want:
            _fail("node %d has depth %d under a parent of depth %d" % (node.index, node.depth, want - 1))
        while stack and stack[-1] != node.parent:
            stack.pop()
        if node.parent != -1 and not stack:
            _fail("node %d is not in its parent's subtree" % node.index)
        for ancestor in stack:
            frame.end[ancestor] = node.index
        frame.children.setdefault(node.parent, []).append(node.index)
        stack.append(node.index)
