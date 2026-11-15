"""What one step gives the ui-scene and ui-fit judges (U06): the scene read through the vocabulary, the rendered tree, and
their association (ui_judge_stage), with the stage findings `scene-vocabulary` and `stage-unmatched`.

A scene node with a field outside the vocabulary, or whose key is not unique in the state, is reported once
(`scene-vocabulary`, error) and takes part in no other check: no check reads a value the gate cannot interpret.
"""

from rigor_lib import ui_judge_stage as stage


class Context:
    def __init__(self, judges, step):
        self.contract = judges.contract
        self.frame = stage.parse_frame(step.obs["frame"])
        self.vocabulary = []                   # (key, fields)
        keys = {}
        for record in step.obs["semantic"]:
            keys[record.fields[0]] = keys.get(record.fields[0], 0) + 1
        nodes = []
        for record in step.obs["semantic"]:
            node, bad = stage.scene_vocabulary(record, self.contract)
            if keys[record.fields[0]] > 1:
                bad = bad + ["key"]
            if bad:
                self.vocabulary.append((record.fields[0], bad, record.raw))
            else:
                nodes.append(node)
        self.scene = nodes
        self.by_key = {node.key: node for node in nodes}
        self.assoc = stage.associate(nodes, self.frame)
        self.roles = frozenset(self.contract.ids("role"))
        self._layers = None

    # ---- the stage findings ---------------------------------------------------------------------------------------
    def stage_findings(self, report):
        seen = set()
        for key, bad, raw in self.vocabulary:
            if (key, tuple(bad)) in seen:
                continue
            seen.add((key, tuple(bad)))
            report.add("scene-vocabulary", ["scene", key, bad], {"stage": "O2", "key": key, "fields": bad},
                       records=[raw])
        for key, reason in self.assoc.unmatched:
            report.add("stage-unmatched", ["scene", key, reason], {"stage": "O2+O3", "side": "scene", "key": key,
                                                                    "reason": reason},
                       target=key, records=[self.by_key[key].raw])
        for index, label in sorted(self.frame.labels.items()):
            if index not in self.assoc.owner and label.own_text != b"" and self.frame.shown(index):
                report.add("stage-unmatched", ["frame-label", index], {"stage": "O2+O3", "side": "frame",
                                                                        "index": index, "reason": "no-scene-node"},
                           records=[self.frame.nodes[index].raw, label.raw])
        return report.found

    # ---- helpers for the checks -----------------------------------------------------------------------------------
    def is_text(self, node):
        return node.role in self.roles

    def matched(self):
        """(scene node, rendered index) of every associated scene node whose rendered node is shown, in scene order."""
        return [(node, self.assoc.match[node.key]) for node in self.scene
                if node.key in self.assoc.match and self.frame.shown(self.assoc.match[node.key])]

    def layer_rows(self):
        return {row["layer"]: row for row in self.contract.rows("input_layer")}

    def layers(self):
        """(scene node, rendered index, input_layer row) of every shown, associated node that declares a layer."""
        if self._layers is None:
            rows = self.layer_rows()
            self._layers = [(node, index, rows[node.input_policy]) for node, index in self.matched()
                            if node.input_policy != "-"]
        return self._layers

    def layer_of(self, index):
        """The rendered index of the nearest declared layer that is `index` or its ancestor, or -1 (the base)."""
        declared = {i for _node, i, _row in self.layers()}
        for candidate in [index] + self.frame.ancestors(index):
            if candidate in declared:
                return candidate
        return -1

    def behind_modal(self, index):
        """A later-painted declared layer that blocks input below (`blocks_input_below`) covers part of the node."""
        box = self.frame.nodes[index].box
        for _node, layer, row in self.layers():
            if row["blocks_input_below"] and layer > index and not self.frame.related(index, layer) \
                    and stage.intersect(box, self.frame.nodes[layer].box) is not None:
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
