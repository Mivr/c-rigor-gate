"""What one step gives the ui-scene and ui-fit judges (U06): the scene read through the vocabulary (ui_judge_vocab), the
rendered tree (ui_judge_stage), their association, and the stage findings: `scene-vocabulary`, `stage-unmatched`,
`stage-text-mismatch`, and `contract-incomplete` for a style token the contract does not know or a style no role names.

A scene node with a field outside the vocabulary, or whose key is not unique in the state, is reported once and takes
part in no other check. Inertness (ruling R5, P004's "declared modal blocker"): an interactive node is inert when it
carries I, or when a later-painted scene node carrying I covers all of its probe points.
"""

import hashlib

from rigor_lib import ui_judge_stage as stage
from rigor_lib import ui_judge_vocab as vocab
from rigor_lib.ui_contract import CARD_ROLES, LAYER_ROLES


class Context:
    def __init__(self, judges, step):
        self.contract = judges.contract
        self.frame = stage.parse_frame(step.obs["frame"])
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
        self.assoc = vocab.associate(nodes, self.frame)
        self.typo = {}                         # key -> (style id, typographic role) of a text-bearing node
        self.incomplete = set()                # (what, name) the contract does not cover
        for node in nodes:
            if node.role in vocab.TEXT_ROLES:
                style, role, problem = vocab.typography(node, self.contract)
                self.typo[node.key] = (style, role)
                if problem is not None:
                    self.incomplete.add(problem)

    # ---- the stage findings ---------------------------------------------------------------------------------------
    def stage_findings(self, report):
        seen = set()
        for key, bad, raw in self.vocabulary:
            if (key, tuple(bad)) not in seen:
                seen.add((key, tuple(bad)))
                report.add("scene-vocabulary", ["scene", key, bad], {"stage": "O2", "key": key, "fields": bad},
                           records=[raw])
        for what, name in sorted(self.incomplete, key=str):
            report.add("contract-incomplete", [what, name], {"what": what, "name": name}, stateless=True)
        for key, reason in self.assoc.unmatched:
            node = self.by_key[key]
            vital = node.interactive or node.role in LAYER_ROLES
            report.add("stage-unmatched", ["scene", key, reason],
                       {"stage": "O2+O3", "side": "scene", "key": key, "reason": reason, "role": node.role},
                       target=key, severity="error" if vital else "info", records=[node.raw])
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
        return report.found

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

    def layer_policy(self, node):
        """The contract's policy of a layer-role node (a scrim's by its card): a policy, None when the contract has no
        row (the caller reports contract-incomplete), or ContractPending raised for a pending row."""
        card = self.card_of(node) if node.role == "scrim" else None
        row = self.contract.layer_row(node.role, card.role if card is not None else None)
        if row is None:
            return None
        return self.contract.row_value("layer", row["id"], "policy")

    def layer_nodes(self):
        """(scene node, rendered index) of every shown, associated node of a layer role."""
        return [(node, index) for node, index in self.matched() if node.role in LAYER_ROLES]

    def layer_of(self, index):
        """The rendered index of the nearest layer-role node that is `index` or its ancestor, or -1 (the base)."""
        layers = {i for _node, i in self.layer_nodes()}
        for candidate in [index] + self.frame.ancestors(index):
            if candidate in layers:
                return candidate
        return -1

    def inert(self, node, index, points):
        """Ruling R5: the node carries I, or a later-painted, shown scene node carrying I covers every probe point."""
        if "I" in node.flags:
            return True
        for other, other_index in self.matched():
            if "I" in other.flags and other_index > index and not self.frame.related(index, other_index):
                box = self.frame.nodes[other_index].box
                if points and all(stage.inside((x, y, x, y), box) for x, y in points):
                    return True
        return False

    def records(self, *indexes):
        out = []
        for index in indexes:
            out.append(self.frame.nodes[index].raw)
            for table in (self.frame.labels, self.frame.fits):
                if index in table:
                    out.append(table[index].raw)
        return out
