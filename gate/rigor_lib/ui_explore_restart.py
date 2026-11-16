"""The declared countdown restart of a tap (U05d; docs/ui-explore.md, "Countdown restart").

A product's pointer entry may restart a visible countdown on every sample it receives (the kiosk's end-of-shift report
restarts its 5-minute deadline on every touch). That shows as a text patch of the countdown node, a semantic label
difference of that node and a frame difference of that label, but not as a `next-due` change, so neither `[ambient]
trace` nor `due_restart_ms` can express it. A catalogue declares the countdown's scene role
(`[ambient] countdown_restart_role`, with provenance); in a TAP step only, after the ambient trace records are set
aside, the residual change of the step counts as "changed nothing" iff ALL of:

- every new patch is `update <key> text <old> <new>` on a key whose semantic records, before and after, all have the
  declared role;
- the semantic trees differ only in the label field of those keys (same records in the same order, every other field
  and every other record byte-identical);
- where frame records are compared: no `life` line, the same frame lines in the same order, and a differing line is
  either a record (`node`, `label`, `fit`, `region`) of a walk index whose `label` record shows the restarted text
  before and after, or the `frame` line with the same size (its crc covers the restarted label's pixels);
- every such patch's text and every such node's label, old and new, hold exactly one run of decimal digits with
  identical text around it, and the new value is >= the old one (a restart never skips a countdown forward);
- nothing else changed: no other new trace record, no deadline change but the declared `due_restart_ms`, no env change.

`declared(...)` returns the restarts ([{"node", "old", "new"}], node keys in their escaped spelling, values as
integers) or None when the change is anything else.
"""

import re

from rigor_lib.ui_explore_grammar import unescape

_ONE_RUN = re.compile(rb"([^0-9]*)([0-9]+)([^0-9]*)")
_ALLOWED = ("patches", "semantic", "frame")      # the parts of `changes` a declared restart may account for
_NODE_RECORDS = ("node", "label", "fit", "region")
_LABEL = 2                                        # the semantic `label` field (SEMANTIC_FIELDS)
_LABEL_TEXT = 13                                  # the frame `label` record's `=`text field (docs/ui-model.md)


def forward(old, new):
    """(old value, new value) when the two texts (bytes) each hold exactly one run of decimal digits, the text around
    the run is identical and the new value is not smaller; None otherwise."""
    a, b = _ONE_RUN.fullmatch(old), _ONE_RUN.fullmatch(new)
    if a is None or b is None or a.group(1) != b.group(1) or a.group(3) != b.group(3):
        return None
    values = int(a.group(2)), int(b.group(2))
    return values if values[1] >= values[0] else None


def _patched_keys(patches):
    """The keys of the new patches when every one is `update <key> text <old> <new>` with a forward text; else None."""
    keys = []
    for patch in patches:
        if patch.fields[0] != "update" or patch.fields[2] != "text" or forward(patch.values[3], patch.values[4]) is None:
            return None
        if patch.fields[1] not in keys:
            keys.append(patch.fields[1])
    return keys


def _roles_hold(lines, keys, role):
    """Every semantic record of every key has the declared role, and every key has at least one record."""
    found = set()
    for line in lines:
        fields = line.split("\t")
        if fields[0] in keys:
            if fields[1] != role:
                return False
            found.add(fields[0])
    return found == set(keys)


def _semantic(before, after, keys, role):
    """{key: (old label field, new label field)} of the records that differ, when the trees differ only in the label
    field of `keys`, whose records all have `role`; None otherwise."""
    if len(before) != len(after) or not (_roles_hold(before, keys, role) and _roles_hold(after, keys, role)):
        return None
    labels = {}
    for old, new in zip(before, after):
        if old == new:
            continue
        a, b = old.split("\t"), new.split("\t")
        if a[0] not in keys or len(a) != len(b) or a[:_LABEL] + a[_LABEL + 1:] != b[:_LABEL] + b[_LABEL + 1:] \
                or a[0] in labels:
            return None
        labels[a[0]] = (a[_LABEL], b[_LABEL])
    return labels


def _label_indexes(before, after, labels):
    """The walk indexes whose frame `label` record shows a restarted node's old text before and its new text after."""
    texts = {("=" + old, "=" + new) for old, new in labels.values()}
    old_text = {f[1]: f[_LABEL_TEXT] for f in (line.split("\t") for line in before) if f[0] == "label"}
    new_text = {f[1]: f[_LABEL_TEXT] for f in (line.split("\t") for line in after) if f[0] == "label"}
    return {i for i in old_text if (old_text[i], new_text.get(i)) in texts}


def _frame(before, after, labels):
    """The frame differs only in records of the restarted labels' walk indexes (and the `frame` line's crc)."""
    if after["life"] or len(before["frame"]) != len(after["frame"]):
        return False
    indexes = _label_indexes(before["frame"], after["frame"], labels)
    for old, new in zip(before["frame"], after["frame"]):
        if old == new:
            continue
        a, b = old.split("\t"), new.split("\t")
        if a[0] != b[0] or len(a) != len(b):
            return False
        if a[0] == "frame" and a[1:3] == b[1:3]:
            continue
        if a[0] not in _NODE_RECORDS or a[1] != b[1] or a[1] not in indexes:
            return False
    return True


def declared(patches, before, after, changed, frame, role):
    """The restarts a tap's residual change consists of (module docstring), or None. `patches` are the step's new patch
    records, `before`/`after` the snapshots, `changed` what `changes` found (non-empty), `frame` whether the frame is
    compared, `role` the declared countdown role."""
    if any(part not in _ALLOWED for part in changed):
        return None
    keys = _patched_keys(patches)
    if not keys:
        return None
    labels = _semantic(before["semantic"], after["semantic"], keys, role)
    if labels is None or (frame and "frame" in changed and not _frame(before, after, labels)):
        return None
    restarts = []
    for key in keys:
        mine = [p for p in patches if p.fields[1] == key]
        old, new = (unescape(labels[key][0]), unescape(labels[key][1])) if key in labels else \
            (mine[0].values[3], mine[-1].values[4])
        values = forward(old, new)
        if values is None:
            return None
        restarts.append({"node": key, "old": values[0], "new": values[1]})
    return restarts
