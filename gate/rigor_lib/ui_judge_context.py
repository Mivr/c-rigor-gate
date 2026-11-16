"""What one step gives the ui-scene and ui-fit judges (U06): the scene read through the vocabulary (ui_judge_vocab), the
rendered tree (ui_judge_stage), their association, what the contract says of each node, and the stage findings:
`scene-vocabulary`, `stage-unmatched`, `stage-text-mismatch`, `stage-unowned-target`, `contract-incomplete`.

A scene node with a field outside the vocabulary, or whose key is not unique in the state, is reported once and takes
part in no other check.

Layers (R6, R8): a node of role scrim, dialog, banner or snackbar is a layer; its policy is the contract's `[[input_layer]]`
table's: the rows of its role (a scrim: of the card that follows it in the scene), `blocks_input_below` true =
capture-modal-inert, false = pass-through; rows of one role that disagree, or none, are contract-incomplete.

Inertness (R7): an interactive node is inert when it carries I, or when it lies under a capture-modal-inert layer whose
rendered scrim (the scrim, or a card without one) is painted later, clickable, drawn with a background opacity above
0 (the "visibly dimmed" proxy) and covers every probe point of the node. A bare I panel grants nothing.
"""

import hashlib

from rigor_lib import ui_judge_contract, ui_judge_identity
from rigor_lib.ui_contract import ContractPending
from rigor_lib import ui_judge_stage as stage
from rigor_lib import ui_judge_vocab as vocab
from rigor_lib.ui_judge_vocab import CARD_ROLES, LAYER_ROLES


class Context:
    def __init__(self, judges, step):
        self.contract = judges.contract
        self.gates = judges.gates                          # U07: the selected judges (who owns a cause)
        self.frame = stage.parse_frame(step.obs["frame"])
        self.ink_records = step.obs.get("ink")             # U07: the ink of a state's first visit, else None
        self.ink_moved = step.obs.get("ink_moved", False)  # the frame re-taken after the ink differed from this one
        self.identity = ui_judge_identity.parse(step.obs.get("identity"))   # U24: None without the probe's identity
        self.vocabulary = []                   # (key, fields, raw)
        counts = {}
        for record in step.obs["semantic"]:
            counts[record.fields[0]] = counts.get(record.fields[0], 0) + 1
        nodes = []
        for record in step.obs["semantic"]:
            node, bad = vocab.read(record, self.contract)
            if counts[record.fields[0]] > 1:
                bad = bad + ["key"]
            if bad:
                self.vocabulary.append((record.fields[0], bad, record.raw))
            else:
                nodes.append(node)
        self.scene = nodes
        self.by_key = {node.key: node for node in nodes}
        self.order = {node.key: i for i, node in enumerate(nodes)}
        accessible = {row["key"] for row in self.contract.rows("element") if row.get("label") == "accessible"}
        self.assoc = vocab.associate(nodes, self.frame, accessible)
        self.incomplete = set()                # (what, name) the contract does not cover
        self.typo, self.scopes, self.policies = {}, {}, {}
        for node in nodes:
            self._resolve(node)
        self.captured = {}                     # target key -> rendered layer parts whose capture overlay-policy owns

    def _resolve(self, node):
        if node.role in vocab.TEXT_ROLES:
            style, role, problem = vocab.typography(node, self.contract)
            self.typo[node.key] = (style, role)
            if problem is not None:
                self.incomplete.add(problem)
            elif role is not None:
                scope = ui_judge_contract.scope_of(self.contract, node.key, role)
                self.scopes[node.key] = scope
                if scope is None:
                    self.incomplete.add(("role-wrap", role))
        if node.role in LAYER_ROLES:
            self.policies[node.key] = self._policy(node)

    def _policy(self, node):
        role = node.role
        if role == "scrim":
            card = self.card_of(node)
            if card is None:
                return None                    # overlay-policy reports it (part `no-card`)
            role = card.role
        rows = ui_judge_contract.layer_rows(self.contract, role)
        blocks = {row["blocks_input_below"] for row in rows}
        if len(blocks) != 1:
            self.incomplete.add(("input-layer", role))
            return None
        return "capture-modal-inert" if blocks.pop() else "pass-through"

    # ---- the stage findings ---------------------------------------------------------------------------------------
    def stage_findings(self, report):
        seen = set()
        for key, bad, raw in self.vocabulary:
            if (key, tuple(bad)) not in seen:
                seen.add((key, tuple(bad)))
                report.add("scene-vocabulary", ["scene", key, bad], {"stage": "O2", "key": key, "fields": bad},
                           records=[raw])
        for what, name in sorted(self.incomplete, key=str):
            report.incomplete(what, name)
        for key, reason in self.assoc.unmatched:
            self._unmatched(report, self.by_key[key], reason)
        for key in self.assoc.mismatch:
            index = self.assoc.match[key]
            report.add("stage-text-mismatch", ["scene", key],
                       {"stage": "O2+O3", "key": key, "role": self.by_key[key].role}, target=key,
                       records=[self.by_key[key].raw] + self.records(index, *self.frame.children.get(index, ())))
        for index, label in sorted(self.frame.labels.items()):
            if index not in self.assoc.owner and index not in self.assoc.claimed and label.own_text != b"" \
                    and self.frame.shown(index):
                name = self.rendered_name(index)
                report.add("stage-unmatched", ["frame-label", name["target"]],
                           {"stage": "O2+O3", "side": "frame", "label": name, "reason": "no-scene-node"},
                           target=name["target"], severity="info", records=self.records(index))
        for index in self.unowned_targets():
            name = self.rendered_name(index)
            report.add("stage-unowned-target", [name["target"]], {"stage": "O2+O3", "node": name},
                       target=name["target"], records=self.records(index))
        return report.found

    def _unmatched(self, report, node, reason):
        vital = node.interactive or node.role in LAYER_ROLES
        found = [self.rendered_name(i) for i in self.candidates(node)]
        report.add("stage-unmatched", ["scene", node.key, reason],
                   {"stage": "O2+O3", "side": "scene", "key": node.key, "reason": reason, "role": node.role,
                    "scene_box": list(node.rect), "candidates": [{"class": c["class"], "box": c["box"]} for c in found]},
                   target=node.key, severity="error" if vital else "info", records=[node.raw])

    def _free(self):
        taken = set(self.assoc.match.values())
        return [n.index for n in self.frame.nodes if not self.frame.is_root(n.index) and n.index not in taken]

    def candidates(self, node):
        """Rendered nodes no scene node has that could be the unmatched one: those carrying its text (a label, or the
        control a label is the child of), or, for a node without text, those compatible with it (no label, and an
        lv_button only for a button or key)."""
        frame, free = self.frame, self._free()
        if node.label != b"":
            out = set()
            for index in free:
                if index in frame.labels and frame.labels[index].own_text == node.label:
                    parent = frame.nodes[index].parent
                    out.add(parent if node.role not in vocab.PURE_TEXT and parent in free else index)
            return sorted(out)
        return [i for i in free if i not in frame.labels and vocab.compatible(node, frame, i)
                and (frame.nodes[i].cls != "lv_button" or node.role in ("button", "key"))]

    def unowned_targets(self):
        """Shown, clickable rendered nodes that no scene node has and that are not part of a scene button or key: a
        control the scene does not know about."""
        frame = self.frame
        controls = {i for key, i in self.assoc.match.items() if self.by_key[key].role in ("button", "key")}
        return [i for i in self._free() if frame.nodes[i].clickable and frame.shown(i)
                and not any(a in controls for a in frame.ancestors(i))]

    # ---- naming a rendered node, never by its walk index ----------------------------------------------------------
    def rendered_name(self, index):
        """A rendered node no scene node is associated with: its class, its box and (a label) 8 hex of the sha256 of
        its text, and a target an exception can name: `node/<class>/<x1>/<y1>/<x2>/<y2>[/<8 hex>]`."""
        node = self.frame.nodes[index]
        parts = ["node", node.cls.lower()] + [str(v) for v in node.box]
        name = {"class": node.cls, "box": list(node.box)}
        if index in self.frame.labels:
            digest = hashlib.sha256(self.frame.labels[index].own_text).hexdigest()[:8]
            parts.append(digest)
            name["text_sha256"] = digest
        name["target"] = "/".join(parts)
        return name

    def name_of(self, index):
        keys = sorted(key for key, i in self.assoc.match.items() if i == index)
        return {"key": keys[0]} if keys else self.rendered_name(index)

    # ---- helpers for the checks -----------------------------------------------------------------------------------
    def role_of(self, node):
        """The typographic role of a text-bearing node, or None (not text-bearing, or the contract cannot say)."""
        return self.typo.get(node.key, (None, None))[1]

    def style_of(self, node):
        return self.typo.get(node.key, (None, None))[0]

    def scope_of(self, node):
        """The [[wrap]] row of a text node (its element's, else its role's), or None (contract-incomplete)."""
        return self.scopes.get(node.key)

    def matched(self):
        """(scene node, rendered index) of every associated scene node whose rendered node is shown, in scene order."""
        return [(node, self.assoc.match[node.key]) for node in self.scene
                if node.key in self.assoc.match and self.frame.shown(self.assoc.match[node.key])]

    def card_of(self, node):
        """The card a scrim belongs to: the next scene node, when its role is a card role; else None."""
        following = self.order[node.key] + 1
        if following < len(self.scene) and self.scene[following].role in CARD_ROLES:
            return self.scene[following]
        return None

    def scrim_of(self, node):
        """The scrim a card belongs to (the scene node just before it, a scrim), or None."""
        before = self.order[node.key] - 1
        if before >= 0 and self.scene[before].role == "scrim":
            return self.scene[before]
        return None

    def layers(self):
        """(layer node, its rendered index, the rendered parts of the layer: the node and its card, the policy or None)
        of every shown, associated layer; a card with a scrim is judged through its scrim."""
        out = []
        for node, index in self.matched():
            if node.role not in LAYER_ROLES or (node.role != "scrim" and self.scrim_of(node) is not None):
                continue
            parts = [index]
            card = self.card_of(node) if node.role == "scrim" else None
            if card is not None and card.key in self.assoc.match:
                parts.append(self.assoc.match[card.key])
            out.append((node, index, parts, self.policies.get(node.key)))
        return out

    def layer_of(self, index):
        """The rendered index of the nearest layer-role node that is `index` or its ancestor, or -1 (the base)."""
        layers = {i for n, i in self.matched() if n.role in LAYER_ROLES}
        for candidate in [index] + self.frame.ancestors(index):
            if candidate in layers:
                return candidate
        return -1

    def inert(self, node, index, points):
        """Ruling R7: the node carries I, or a later-painted capture-modal-inert layer's rendered scrim that is clickable
        and drawn with a background opacity above 0 covers every probe point."""
        if "I" in node.flags:
            return True
        frame = self.frame
        for _layer, shield, _parts, policy in self.layers():
            rendered = frame.nodes[shield]
            if policy != "capture-modal-inert" or shield <= index or frame.related(index, shield) \
                    or not rendered.clickable or rendered.bg_opa_drawn <= 0 or not frame.shown(shield):
                continue
            box = frame.visible_box(shield)
            if points and box is not None and all(stage.inside((x, y, x, y), box) for x, y in points):
                return True
        return False

    # ---- shared with the explorer's tap judges (U05e; the judges above do not call these) ---------------------------
    def inert_target(self, node, index):
        """R7 for a tap's target: `inert` with exactly the probe points the geometric checks use (the grid, and with
        the ppi the disc's corners)."""
        from rigor_lib.ui_judge_geom import Probe
        try:
            radius = self.contract.mm_to_px(self.contract.get("thresholds", "probe_disc_radius_mm"))
        except ContractPending:
            radius = None
        probe = Probe(self.frame.nodes[index].box, self.contract.get("thresholds", "probe_grid_pct"), radius)
        return self.inert(node, index, probe.inert_points())

    def tap_outside(self, node):
        """Whether the contract's `[[input_layer]]` rows of a scrim's layer (its card's role) say a tap outside the card
        dismisses it: True, False, or None when the rows disagree, are missing or the scrim has no card."""
        card = self.card_of(node) if node.role == "scrim" else None
        if card is None:
            return None
        values = {row["tap_outside_dismisses"] for row in ui_judge_contract.layer_rows(self.contract, card.role)}
        return values.pop() if len(values) == 1 else None

    def records(self, *indexes):
        out = []
        for index in indexes:
            out.append(self.frame.nodes[index].raw)
            for table in (self.frame.labels, self.frame.fits):
                if index in table:
                    out.append(table[index].raw)
        return out
