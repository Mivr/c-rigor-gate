"""Shared fixtures of the ui-scene and ui-fit judge tests (no tests here): hand-built observations of one step, the
semantic records (O2) and the frame-facts lines (O3) written as the probe writes them, a test contract, and an
independent recomputation of the finding id (from docs/ui-judges.md with hashlib and json only)."""

import copy
import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from rigor_lib import ui_contract
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_explore_judges import PathSoFar
from rigor_lib.ui_explore_run import Step
from rigor_lib.ui_judge_findings import JudgeSet

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CANARY_CONTRACT = REPO / "selftest" / "ui_canary_product" / "canary.toml"
KEY = SimpleNamespace(fields=("role",))
TODAY = datetime.date(2026, 11, 16)
# the style tokens of the canary contract (selftest/ui_canary_product/canary.toml)
TOKENS = {"title": 1, "body": 2, "caption": 3, "btn": 5, "lang_on": 6, "lang_off": 7, "small_body": 8, "big_body": 9}
STATE_KEY = "k" * 64
OPEN = "open 1000 7"


def esc(data):
    out = []
    for byte in data:
        if byte == 0x5c:
            out.append("\\\\")
        elif byte == 0x09:
            out.append("\\t")
        elif byte == 0x0a:
            out.append("\\n")
        elif 0x20 <= byte <= 0x7e:
            out.append(chr(byte))
        else:
            out.append("\\x%02x" % byte)
    return "".join(out)


def sem(key, role, label, rect, intent="-", flags="-", style=0, importance="-", policy="-", wrap="-", enabled=1):
    """One semantic record in the scene vocabulary (docs/ui-judges.md): `style` a token number or a canary style
    name, `flags` letters."""
    text = label.encode("utf-8") if isinstance(label, str) else label
    x, y, w, h = rect
    token = str(TOKENS[style]) if style in TOKENS else str(style)
    return "\t".join([key, role, esc(text), str(x), str(y), str(w), str(h), str(enabled), intent, flags, token,
                      importance, policy, wrap])


class Tree:
    """A rendered tree built node by node in walk order; `lines()` gives the frame reply's records."""

    def __init__(self, width=320, height=240):
        self.width, self.height, self.nodes = width, height, []
        self.root = self.node(-1, "lv_obj", (0, 0, width - 1, height - 1), clickable=1, bg=255)

    def node(self, parent, cls, box, hidden=0, clickable=0, clip=-1, scroll=-1, bg=0, exact=1, grad=0, image=0,
             colour="ffffff"):
        depth = 0 if parent == -1 else self.nodes[parent]["depth"] + 1
        self.nodes.append({"parent": parent, "depth": depth, "cls": cls, "box": box, "hidden": hidden,
                           "clickable": clickable, "clip": clip, "scroll": scroll, "bg": bg, "exact": exact,
                           "grad": grad, "image": image, "label": None, "fit": None, "colour": colour})
        return len(self.nodes) - 1

    def label(self, parent, text, box, natural=None, laid=None, lines=1, line_h=16, long_mode=0, full=None,
              drawn=1, unsupported=0, glyphs="auto", visible="auto", missing=0, clipped=0, hidden=0, fit=True,
              clip=-1):
        """A label; its line height defaults to 16, the canary contract's line height of every style."""
        index = self.node(parent, "lv_label", box, hidden=hidden, clip=clip)
        w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.nodes[index]["label"] = {"text": data, "full": full, "natural": natural or (w, h),
                                      "laid": laid or (w, h), "lines": lines, "line_h": line_h, "long": long_mode}
        if fit:
            gbox = "%d,%d,%d,%d" % (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1) if glyphs == "auto" else glyphs
            vbox = "%d,%d,%d,%d" % box if visible == "auto" else visible
            self.nodes[index]["fit"] = {"drawn": drawn, "unsupported": unsupported, "glyphs": gbox, "visible": vbox,
                                        "missing": missing, "clipped": clipped}
        return index

    def lines(self):
        out = ["lvprobe\t1\t%d" % len(self.nodes), "frame\t%d\t%d\t0badf00d" % (self.width, self.height)]
        for i, n in enumerate(self.nodes):
            out.append("\t".join(["node", str(i), str(n["parent"]), str(n["depth"]), n["cls"]]
                                 + [str(v) for v in n["box"]]
                                 + [str(n["hidden"]), str(n["clickable"]), str(n["clip"]), str(n["scroll"]), "0", "0",
                                    n["colour"], str(n["bg"]), str(n["bg"]), str(n["exact"]), str(n["grad"]),
                                    str(n["image"])]))
            label = n["label"]
            if label is not None:
                full = "-" if label["full"] is None else "=" + esc(label["full"].encode("utf-8"))
                out.append("\t".join(["label", str(i), "-", str(label["line_h"]), "0", "1", str(label["long"]),
                                      "0" if label["full"] is None else "1", str(label["lines"]),
                                      str(label["natural"][0]), str(label["natural"][1]), str(label["laid"][0]),
                                      str(label["laid"][1]), "=" + esc(label["text"]), full]))
            fit = n["fit"]
            if fit is not None:
                out.append("\t".join(["fit", str(i), str(fit["drawn"]), str(fit["unsupported"]), fit["glyphs"],
                                      fit["visible"], str(fit["missing"]), str(fit["clipped"])]))
            out.append("region\t%d\t00000000" % i)
        return out


def contract(edit=None):
    text = CANARY_CONTRACT.read_text()
    if edit is not None:
        text = edit(text)
    return ui_contract.loads(text)


def pending(text, line_start, replacement):
    """`text` with the line that starts with `line_start` replaced."""
    out = []
    for line in text.splitlines(keepends=True):
        out.append(replacement + "\n" if line.startswith(line_start) else line)
    return "".join(out)


def step(semantic, tree, word="ev", index=1):
    s = Step(index, word)
    s.obs = {"semantic": tuple(parse_record("semantic", line) for line in semantic),
             "frame": tuple(parse_typed_line(FRAME_FIELDS, line) for line in tree.lines()),
             "patches": (), "trace": (), "due": None, "env": ()}
    s.key, s.proj, s.origin = STATE_KEY, {"nodes": [], "facts": {}}, 1000
    return s


def run(semantic, tree, gates=("ui-scene", "ui-fit"), the_contract=None, today=None, finish=False):
    """The findings of one step (and, with `finish`, of the end of the run), without the private evidence key."""
    judges = JudgeSet(list(gates), the_contract or contract(), KEY, today or TODAY)
    open_step = Step(0, OPEN)
    found = judges.step_judge(step(semantic, tree), PathSoFar([open_step], 1), None)
    if finish:
        found = found + judges.finish(OPEN)
    return [{k: v for k, v in copy.deepcopy(f).items() if k != "_evidence"} for f in found]


def expected_id(gate, check, identity, stateless=False):
    data = json.dumps([gate, check, identity if stateless else [identity, STATE_KEY]], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    return "%s.%s/%s" % (gate, check, hashlib.sha256(data).hexdigest()[:12])


def checks(found, severity=None):
    return sorted(f["check"] for f in found if severity is None or f["severity"] == severity)


# ---- the clean base scene ------------------------------------------------------------------------------------------
LANG = [sem("lang_bg", "button", "BG", (216, 8, 48, 48), intent="8:0", style="lang_on"),
        sem("lang_en", "button", "EN", (272, 8, 48, 48), intent="8:1", style="lang_off")]


def add_lang(tree):
    """The BG/EN switch (the canary contract's toggle group): two buttons of different fill."""
    for x, text, colour in ((216, "BG", "2b4678"), (272, "EN", "282a2f")):
        button = tree.node(0, "lv_button", (x, 8, x + 47, 55), clickable=1, bg=255, colour=colour)
        tree.label(button, text, (x + 14, 24, x + 33, 39))


def base(lang=False):
    """(semantic lines, tree) of a correct state: a title, a body text and one button with its label; with `lang`, the
    BG/EN switch after them."""
    tree = Tree()
    tree.label(0, "Title", (8, 8, 207, 31))
    tree.label(0, "Body text", (8, 40, 207, 63))
    button = tree.node(0, "lv_button", (8, 100, 107, 149), clickable=1, bg=255)
    tree.label(button, "OK", (48, 117, 67, 132))
    semantic = [sem("title", "text", "Title", (8, 8, 200, 24), style="title"),
                sem("body", "text", "Body text", (8, 40, 200, 24), style="body"),
                sem("ok", "button", "OK", (8, 100, 100, 50), intent="1:0", style="btn")]
    if lang:
        add_lang(tree)
        semantic += LANG
    return semantic, tree
