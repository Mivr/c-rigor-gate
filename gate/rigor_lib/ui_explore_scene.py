"""State-scoped taps of `rigor ui-explore` (U05e; P004 3.4, 4.3 U2/U3; docs/ui-explore.md "Scene taps").

With `taps = { scope = "scene", ... }` the u2 and u3 taps of a state are derived from that state's scene and rendered
tree (the observation of the step before the tap), not fixed points:
  u2  `tap@<key>#<i>`: for every enabled interactive scene node (an intent, enabled, neither I nor D) associated with a
      shown rendered node (docs/ui-judges.md, the association), point 0 is the centre of its visible box and points
      1.. the other points of the inset grid (`probe_points` of ui_judge_geom: the contract's `probe_grid_pct` with
      --contract, else the catalogue's `grid_pct`), in sorted order;
  u3  `blank#<i>`: the centre of every disabled control (a button or key that is not interactive), then one point of
      every shown scrim outside its card (the first grid point of the scrim's box not in the card), then the grid
      points of the display that lie in no interactive node and no layer; duplicates dropped.
Point index, then scene order (every node's centre first): the same state gives the same words, so a word replays.
Each class is capped at `max_per_state` per state; a capped state is the info finding `taps-capped` once per state and
class. A word that names no point of the state it is sent in is the outcome `unbound` (no input is sent).
"""

import re
from types import SimpleNamespace

from rigor_lib import ui_judge_stage as stage
from rigor_lib import ui_judge_vocab as vocab
from rigor_lib.errors import InternalError
from rigor_lib.ui_contract import ContractPending
from rigor_lib.ui_explore_catalogue import Event
from rigor_lib import ui_explore_layers as layers
from rigor_lib.ui_explore_grammar import FRAME_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_explore_words import snapshot_of
from rigor_lib.ui_judge_geom import centre, probe_points

TAP_WORD = re.compile(r"tap@([^\t]{1,1024})#(0|[1-9][0-9]{0,3})")
BLANK_WORD = re.compile(r"blank#(0|[1-9][0-9]{0,3})")
_NO_CONTRACT = SimpleNamespace(ids=lambda table: ())     # vocab.read without a contract: no wrap scope is known
CONTROL_ROLES = ("button", "key")


def is_scene_word(word):
    return TAP_WORD.fullmatch(word) is not None or BLANK_WORD.fullmatch(word) is not None


class View:
    """One state's scene (the vocabulary's nodes, unique keys only), rendered tree and association, from a snapshot
    (`semantic` and `frame` raw lines); `ok` is False when the frame facts cannot be read as a tree."""

    def __init__(self, snapshot, contract):
        self.ok = False
        try:
            records = [parse_record("semantic", line) for line in snapshot["semantic"]]
            self.frame = stage.parse_frame([parse_typed_line(FRAME_FIELDS, line) for line in snapshot["frame"]])
        except (InternalError, ValueError):
            return
        keys = [r.fields[0] for r in records]
        nodes = [vocab.read(r, contract or _NO_CONTRACT)[0] for r in records if keys.count(r.fields[0]) == 1]
        self.scene = [n for n in nodes if n is not None]
        self.assoc = vocab.associate(self.scene, self.frame)
        self.records, self.ok = records, True

    def box(self, node):
        """The visible box of the shown rendered node associated with a scene node, or None."""
        index = self.assoc.match.get(node.key)
        if index is None or not self.frame.shown(index):
            return None
        return self.frame.visible_box(index)


def u2_points(view, grid):
    """[(word, (x, y), rendered index)] of the state's u2 scene taps."""
    per_node = []
    for node in view.scene:
        box = view.box(node) if node.interactive else None
        if box is None:
            continue
        mid = centre(box)
        points = [mid] + [p for p in probe_points(box, grid) if p != mid]
        per_node.append([("tap@%s#%d" % (node.key, i), p, view.assoc.match[node.key]) for i, p in enumerate(points)])
    # point i of every node before point i + 1 of any: a cap keeps every node's centre first
    return [items[i] for i in range(max((len(x) for x in per_node), default=0)) for items in per_node if i < len(items)]


def _scrim_points(view, grid):
    out = []
    for position, node in enumerate(view.scene):
        box = view.box(node) if node.role == "scrim" else None
        if box is None:
            continue
        card = view.scene[position + 1] if position + 1 < len(view.scene) else None
        card_box = view.box(card) if card is not None and card.role in vocab.CARD_ROLES else None
        free = [p for p in probe_points(box, grid) if card_box is None or not stage.inside((*p, *p), card_box)]
        out += free[:1]
    return out


def u3_points(view, grid):
    """[(word, (x, y), None)] of the state's u3 scene taps."""
    points = [centre(view.box(n)) for n in view.scene if n.role in CONTROL_ROLES and not n.interactive and view.box(n)]
    points += _scrim_points(view, grid)
    taken = [view.box(n) for n in view.scene if (n.interactive or n.role in vocab.LAYER_ROLES) and view.box(n)]
    display = (0, 0, view.frame.width - 1, view.frame.height - 1)
    points += [p for p in probe_points(display, grid) if not any(stage.inside((*p, *p), b) for b in taken)]
    unique = []
    for point in points:
        if point not in unique:
            unique.append(point)
    return [("blank#%d" % i, p, None) for i, p in enumerate(unique)]


class Scene:
    """The scene taps of a run: the catalogue's `taps` table and the contract (for its probe grid), or None."""

    def __init__(self, catalogue, contract):
        self.catalogue, self.contract, self.spec = catalogue, contract, catalogue.taps
        self.grid = self.spec.grid_pct if self.spec is not None else None
        if contract is not None:
            try:
                self.grid = tuple(contract.get("thresholds", "probe_grid_pct"))
            except ContractPending:
                pass

    @property
    def scoped(self):
        return self.spec is not None and self.spec.scope == "scene"

    def points(self, snapshot):
        """(u2 points, u3 points, the uncapped counts) of the state of a snapshot; ([], [], (0, 0)) when unread."""
        view = View(snapshot, self.contract)
        if not self.scoped or not view.ok:
            return [], [], (0, 0)
        u2, u3 = u2_points(view, self.grid), u3_points(view, self.grid)
        cap = self.spec.max_per_state
        return u2[:cap], u3[:cap], (len(u2), len(u3))

    def state_words(self, step):
        """(the words of a step's state, [(class, uncapped count)] of each class the cap cut)."""
        u2, u3, counts = self.points(snapshot_of(step.obs))
        capped = [(cls, count) for cls, count in zip(("u2", "u3"), counts) if count > self.spec.max_per_state]
        return [word for word, _, _ in u2 + u3], capped

    def resolve(self, word, snapshot):
        """(the tap Event of a scene word in the state of `snapshot`, the rendered index it aims at), or None."""
        u2, u3, _ = self.points(snapshot)
        for cls, items in (("u2", u2), ("u3", u3)):
            for name, (x, y), aim in items:
                if name == word:
                    return Event(word, cls, (("x", x), ("y", y))), aim
        return None

    def judge_apply(self, step, event, snapshot):
        """U05e, with a contract and `taps` `intent_node`: an intent input (u1, u5, a pad macro's enter) whose scene
        node is inert under R7 in the state before expects no effect: `missed` becomes `inert` (no intent-missed), an
        accepted one is `blocked-target-live`."""
        named = self.spec.intent_node if self.spec is not None else None
        if self.contract is None or named is None or step.result not in ("ok", "missed"):
            return
        intent, arg = (event.get("intent"), event.get("arg")) if event.cls in ("u1", "u5") else \
            (event.get("enter_intent"), 0) if event.cls == "u4" and event.get("via") == "pad" else (None, None)
        ctx = layers.context(self.contract, snapshot) if intent is not None else None
        if ctx is None:
            return
        want = str(intent) if named == "key" else "%d:%d" % (intent, arg)
        node = next((n for n in ctx.scene if (n.key if named == "key" else n.intent) == want), None)
        index = ctx.assoc.match.get(node.key) if node is not None else None
        try:
            inert = index is not None and node.interactive and ctx.inert_target(node, index)
        except ContractPending:
            inert = False
        if not inert:
            return
        step.outcome.append("layer inert %s" % node.key)
        if step.result == "missed":
            step.applies[-1] = "inert"
        else:
            step.blocked = {"layer": None, "target": node.key, "changed": ["intent"]}
