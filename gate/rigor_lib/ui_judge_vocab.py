"""The scene (P004 2.1 stage O2) as the ui-scene and ui-fit judges read it, and its association with the rendered tree
(U06; docs/ui-judges.md, "The scene vocabulary" and "Scene to rendered").

The vocabulary is the gate's (orchestrator rulings R1 to R6): `role` is a structural role of a closed list; `style` is
the product's numeric style token, whose typographic role the judges take from the contract (token -> [[style]] ->
[[role]] or [[style_role]]); `flags` is a string of letters; `importance`, `input_policy` and `wrap_policy` are `-` by
design (the judges take them from the contract) and a present value must be one the contract could say. A value outside
the vocabulary is `scene-vocabulary`; nothing is guessed.

The association: a scene node with rect R is paired with a rendered node whose box is R (lvprobe's inclusive coords),
never a screen or layer root. Equal rects are paired by rank: the k-th scene node with rect R (scene pre-order) is the
k-th rendered node with box R (walk order) when both counts agree; otherwise every scene node with that rect is
`ambiguous` (`absent` when no rendered node has it), and so are they when any pair is incompatible (a button or key
needs an `lv_button`, a text or countdown a label, a card a drawn background, a node with an intent a clickable
object). A paired node whose text is not the rendered one is `stage-text-mismatch`, except a node whose contract
element declares its label accessible only (ui-look.md 4.3, X6).
"""

import re
from dataclasses import dataclass

from rigor_lib import ui_judge_contract
from rigor_lib.ui_judge_contract import LAYER_ROLES      # defined once, with the contract's input-layer naming rule

STRUCTURAL_ROLES = ("root", "panel", "text", "button", "key", "countdown", "scrim", "dialog", "banner", "snackbar")
CARD_ROLES = ("dialog", "banner", "snackbar")

FLAG_LETTERS = "IDWNSHX"          # inert, disabled, warn, notice, scroll; hidden, selected (not emitted by lockers yet)
TEXT_ROLES = frozenset(("text", "button", "key", "countdown"))     # the structural roles whose style is typographic
PURE_TEXT = frozenset(("text", "countdown"))
_INTENT = re.compile(r"(0|[1-9][0-9]{0,9}):(0|-?[1-9][0-9]{0,9})")
_TOKEN = re.compile(r"0|[1-9][0-9]{0,5}")
_IMPORTANCE = re.compile(r"[1-9]")
POLICIES = ("pass-through", "capture-modal-inert", "capture-and-dismiss")


@dataclass(frozen=True)
class SNode:
    """One semantic record. `rect` is the inclusive box of x, y, w, h (display pixels)."""
    key: str
    role: str
    label: bytes
    x: int
    y: int
    w: int
    h: int
    enabled: bool
    intent: str
    flags: frozenset
    token: int
    importance: str
    input_policy: str
    wrap_policy: str
    raw: str

    @property
    def rect(self):
        return (self.x, self.y, self.x + self.w - 1, self.y + self.h - 1)

    @property
    def hidden(self):
        return "H" in self.flags

    @property
    def interactive(self):
        """A node a visitor can operate: an intent, enabled, not flagged inert (I) or disabled (D)."""
        return self.intent != "-" and self.enabled and not self.flags & {"I", "D"}


def _flags(text):
    if text == "-":
        return frozenset()
    if text == "" or len(set(text)) != len(text) or not set(text) <= set(FLAG_LETTERS):
        return None
    return frozenset(text)


def read(record, contract):
    """(SNode or None, the fields that break the vocabulary)."""
    f, v = record.fields, record.values
    flags = _flags(f[9])
    checks = (("role", f[1] in STRUCTURAL_ROLES), ("flags", flags is not None),
              ("intent", f[8] == "-" or _INTENT.fullmatch(f[8]) is not None),
              ("style", _TOKEN.fullmatch(f[10]) is not None),
              ("importance", f[11] == "-" or _IMPORTANCE.fullmatch(f[11]) is not None),
              ("input_policy", f[12] == "-" or f[12] in POLICIES),
              ("wrap_policy", f[13] == "-" or f[13] in contract.ids("wrap")))
    bad = [name for name, ok in checks if not ok]
    if bad:
        return None, bad
    return SNode(key=f[0], role=f[1], label=v[2], x=int(f[3]), y=int(f[4]), w=int(f[5]), h=int(f[6]),
                 enabled=f[7] == "1", intent=f[8], flags=flags, token=int(f[10]), importance=f[11],
                 input_policy=f[12], wrap_policy=f[13], raw=record.raw), []


def typography(node, contract):
    """(style id, typographic role, problem) of a node of a text-bearing structural role; problem is None, or
    ("style-token", token) when the contract has no such token, or ("style-role", style) when no role names it."""
    style = ui_judge_contract.style_by_token(contract, node.token)
    if style is None:
        return None, None, ("style-token", node.token)
    role = ui_judge_contract.role_of_style(contract, style["id"])
    if role is None:
        return style["id"], None, ("style-role", style["id"])
    return style["id"], role, None


# ---- the association ----------------------------------------------------------------------------------------------
@dataclass
class Association:
    """match: key -> rendered index; text: key -> the label carrying its text, or None; unmatched: [(key, reason)];
    mismatch: [key] (rect paired, text not); owner: label index -> key; claimed: the labels of mismatched nodes (they
    have a scene node, whose text is not theirs)."""
    match: dict
    text: dict
    unmatched: list
    mismatch: list
    owner: dict
    claimed: set


def _carrier(frame, index, label):
    """(the text matches, the label index carrying it) of a scene label against rendered node `index`."""
    if index in frame.labels:
        return frame.labels[index].own_text == label, index
    if label == b"":
        return True, None
    carriers = [c for c in frame.children.get(index, ()) if c in frame.labels and frame.labels[c].own_text == label]
    return len(carriers) == 1, carriers[0] if len(carriers) == 1 else None


def compatible(node, frame, index):
    """Whether a rendered node can be the scene node at all (checked for every pair of the rank pairing)."""
    rendered = frame.nodes[index]
    if node.role in ("button", "key") and rendered.cls != "lv_button":
        return False
    if node.role in PURE_TEXT and index not in frame.labels:
        return False
    if node.role in CARD_ROLES and rendered.bg_opa_drawn <= 0:
        return False
    return node.intent == "-" or rendered.clickable


def associate(scene, frame, accessible=frozenset()):
    """Pair every non-root scene node with a rendered node (rect = box, by rank among equal boxes, every pair
    compatible); `accessible`: the keys whose label is accessible only (not compared with the drawn text)."""
    rendered, wanted = {}, {}
    for node in frame.nodes:
        if not frame.is_root(node.index):
            rendered.setdefault(node.box, []).append(node.index)
    for node in scene:
        if node.role != "root":
            wanted.setdefault(node.rect, []).append(node)
    out = Association({}, {}, [], [], {}, set())
    for rect, nodes in wanted.items():
        found = rendered.get(rect, [])
        if len(found) != len(nodes) or not all(compatible(n, frame, i) for n, i in zip(nodes, found)):
            out.unmatched.extend((n.key, "absent" if not found else "ambiguous") for n in nodes)
            continue
        for node, index in zip(nodes, found):
            out.match[node.key] = index
            ok, carrier = (True, None) if node.key in accessible else _carrier(frame, index, node.label)
            out.text[node.key] = carrier if ok else None
            if not ok:
                out.mismatch.append(node.key)
                out.claimed |= {i for i in [index] + frame.children.get(index, []) if i in frame.labels}
            elif carrier is not None:
                out.owner[carrier] = node.key
    out.unmatched.sort()
    out.mismatch.sort()
    return out
