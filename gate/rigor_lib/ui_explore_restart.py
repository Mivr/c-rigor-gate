"""The declared countdown restart of a tap (U05d; docs/ui-explore.md, "Countdown restart").

A product's pointer entry may restart a visible countdown on every sample it receives (the kiosk's end-of-shift report
restarts its 5-minute deadline on every touch). That shows as a text patch of the countdown node, a semantic label
difference of that node and a frame difference of that label, but not as a `next-due` change, so neither `[ambient]
trace` nor `due_restart_ms` can express it. A catalogue declares the countdown's scene role
(`[ambient] countdown_restart_role`, with provenance); in a TAP step only, after the ambient trace records are set
aside, the residual change of the step counts as "changed nothing" iff ALL of:

- every new patch is `update <key> text <old> <new>` on a key whose semantic records, before and after, all have the
  declared role, and the patches of each key form a chain from its old label to its new one (first old = the old label,
  each old = the previous new, last new = the new label, compared unescaped);
- the semantic trees differ only in the label field of exactly those keys (same records in the same order, every other
  field and every other record byte-identical);
- where frame records are compared (`frame_reason`): no `life` line, the same frame lines in the same order, the
  `lvprobe` line unchanged, the `frame` line changed in its crc only; each restarted key matches exactly ONE walk index
  (its `label` record shows the old label before and the new one after, its node of the same class); of that index the
  `node` record may differ only in its box, and the box only as the text's laid size did (`_box_follows_text`), the
  `label` record only in dotted, lines, natural and laid size, text and
  full text, `fit` and `region` freely; of any other index only the `region` record may differ, and only when that
  index's `node` record is unchanged and its box intersects the countdown's box before or after (a region is the hash
  of the pixels inside a node's box, so every node that covers the label repaints with it);
- every patch's text and every such node's label, old and new, hold exactly one run of 1 to 18 decimal digits with
  identical text around it, and the new value is >= the old one (a restart never skips a countdown forward);
- nothing else changed: no other new trace record, no deadline change but the declared `due_restart_ms`, no env change.

`verdict(...)` returns (restarts, None) or (None, the reason the change is not a declared restart); `restarts` is
[{"node", "old", "new"}], node keys in their escaped spelling, values as integers.
"""

import re

from rigor_lib.ui_explore_grammar import unescape

_ONE_RUN = re.compile(rb"([^0-9]*)([0-9]{1,18})([^0-9]*)")   # at most 18 digits: the value fits, int() stays cheap
_ALLOWED = ("patches", "semantic", "frame")      # the parts of `changes` a declared restart may account for
_INDEXED = ("node", "label", "fit", "region")    # frame records that belong to one walk index (their field 1)
_LABEL = 2                                        # the semantic `label` field (SEMANTIC_FIELDS)
_LABEL_TEXT = 13                                  # the frame `label` record's `=`text field (docs/ui-model.md)
_LABEL_FIXED = (2, 3, 4, 5, 6)                    # its font id, line_h, align, align_drawn and long
_BOX = slice(5, 9)                                # the `node` record's x1, y1, x2, y2
_LAID = (11, 12)                                  # the `label` record's laid_w and laid_h


def forward(old, new):
    """(old value, new value) when the two texts (bytes) each hold exactly one run of 1 to 18 decimal digits, the text
    around the run is identical and the new value is not smaller; None otherwise."""
    a, b = _ONE_RUN.fullmatch(old), _ONE_RUN.fullmatch(new)
    if a is None or b is None or a.group(1) != b.group(1) or a.group(3) != b.group(3):
        return None
    values = int(a.group(2)), int(b.group(2))
    return values if values[1] >= values[0] else None


def _patched_keys(patches):
    """(keys, None) when every new patch is `update <key> text <old> <new>` with a forward text, else (None, why)."""
    keys = []
    for patch in patches:
        if patch.fields[0] != "update" or patch.fields[2] != "text":
            return None, "patch op"
        if forward(patch.values[3], patch.values[4]) is None:
            return None, "patch text"
        if patch.fields[1] not in keys:
            keys.append(patch.fields[1])
    return (keys, None) if keys else (None, "no patch")


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


def _semantic(before, after, keys):
    """({key: (old label field, new label field)}, None) when the trees differ only in the label field of exactly
    `keys`, one record each; else (None, why)."""
    if len(before) != len(after):
        return None, "semantic shape"
    labels = {}
    for old, new in zip(before, after):
        if old == new:
            continue
        a, b = old.split("\t"), new.split("\t")
        if a[0] not in keys or len(a) != len(b) or a[:_LABEL] + a[_LABEL + 1:] != b[:_LABEL] + b[_LABEL + 1:] \
                or a[0] in labels:
            return None, "semantic"
        labels[a[0]] = (a[_LABEL], b[_LABEL])
    return (labels, None) if set(labels) == set(keys) else (None, "patch without a label change")


def _chained(patches, key, old, new):
    """The key's patches lead from its old label to its new one, each starting where the one before ended."""
    text = unescape(old)
    for patch in patches:
        if patch.fields[1] == key:
            if patch.values[3] != text:
                return False
            text = patch.values[4]
    return text == unescape(new)


def _indexed(lines, kind):
    return {f[1]: f for f in (line.split("\t") for line in lines) if f[0] == kind}


def _countdown_indexes(before, after, labels):
    """(the one walk index per restarted key, None) or (None, why): its `label` record shows the old label before and
    the new one after, and its node keeps its class."""
    old_text, new_text = _indexed(before, "label"), _indexed(after, "label")
    old_node, new_node = _indexed(before, "node"), _indexed(after, "node")
    found = []
    for old, new in labels.values():
        match = [i for i in old_text if old_text[i][_LABEL_TEXT] == "=" + old and i in new_text
                 and new_text[i][_LABEL_TEXT] == "=" + new and i in old_node and i in new_node
                 and old_node[i][4] == new_node[i][4]]
        if len(match) != 1:
            return None, "frame label match"
        found.append(match[0])
    return (found, None) if len(set(found)) == len(found) else (None, "frame label match")


def _box(fields):
    return tuple(int(v) for v in fields[_BOX])


def _meets(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _box_follows_text(old_node, new_node, old_label, new_label):
    """The countdown's own box changed only as its text's laid size did: its width and height change by exactly the
    `label` record's laid_w and laid_h change, and x1 / y1 each move by at most that width / height change (the label's
    alignment). So a product cannot grow the box on a tap to let every node meeting it change its region."""
    (x1, y1, x2, y2), (u1, v1, u2, v2) = _box(old_node), _box(new_node)
    dw, dh = (u2 - u1) - (x2 - x1), (v2 - v1) - (y2 - y1)
    laid = [int(new_label[i]) - int(old_label[i]) for i in _LAID]
    return [dw, dh] == laid and abs(u1 - x1) <= abs(dw) and abs(v1 - y1) <= abs(dh)


def _record_allowed(a, b, own, covers):
    """Whether one differing indexed record may differ: `own` the countdown's index, `covers` (another index) whether
    its node is unchanged and its box meets the countdown's."""
    if own and a[0] == "node":
        return a[:_BOX.start] + a[_BOX.stop:] == b[:_BOX.start] + b[_BOX.stop:]
    if own and a[0] == "label":
        return all(a[i] == b[i] for i in _LABEL_FIXED)
    return own or (a[0] == "region" and covers)


def frame_reason(before, after, life, labels):
    """None when the frame lines `before` -> `after` (without `taps` and `life`) differ only as a repaint of the
    restarted labels (`labels`: {key: (old, new)}, escaped) allows, `life` being the after frame's `life` lines; else
    the reason."""
    if life:
        return "frame life"
    if len(before) != len(after):
        return "frame shape"
    indexes, why = _countdown_indexes(before, after, labels)
    if why:
        return why
    old_node, new_node = _indexed(before, "node"), _indexed(after, "node")
    old_label, new_label = _indexed(before, "label"), _indexed(after, "label")
    for i in indexes:
        if _box(old_node[i]) != _box(new_node[i]) and \
                not _box_follows_text(old_node[i], new_node[i], old_label[i], new_label[i]):
            return "frame record node %s" % i
    boxes = [_box(nodes[i]) for i in indexes for nodes in (old_node, new_node)]
    for old, new in zip(before, after):
        if old == new:
            continue
        a, b = old.split("\t"), new.split("\t")
        if a[0] == b[0] == "frame" and a[:3] == b[:3]:
            continue
        if a[0] != b[0] or a[0] not in _INDEXED or a[1] != b[1]:
            return "frame record %s" % a[0]
        i = a[1]
        covers = old_node.get(i) is not None and old_node.get(i) == new_node.get(i) \
            and any(_meets(_box(old_node[i]), box) for box in boxes)
        if not _record_allowed(a, b, i in indexes, covers):
            return "frame record %s %s" % (a[0], i)
    return None


def verdict(patches, before, after, changed, frame, role):
    """(restarts, None) when a tap's residual change is a declared countdown restart (module docstring), else (None,
    why). `patches` are the step's new patch records, `before`/`after` the snapshots, `changed` what `changes` found
    (non-empty), `frame` whether the frame is compared, `role` the declared countdown role."""
    other = [part for part in changed if part not in _ALLOWED]
    if other:
        return None, "part " + other[0]
    keys, why = _patched_keys(patches)
    if why:
        return None, why
    if not (_roles_hold(before["semantic"], keys, role) and _roles_hold(after["semantic"], keys, role)):
        return None, "role"
    labels, why = _semantic(before["semantic"], after["semantic"], keys)
    if why:
        return None, why
    if not all(_chained(patches, key, *labels[key]) for key in keys):
        return None, "patch chain"
    restarts = []
    for key in keys:
        values = forward(unescape(labels[key][0]), unescape(labels[key][1]))
        if values is None:
            return None, "label text"
        restarts.append({"node": key, "old": values[0], "new": values[1]})
    why = frame_reason(before["frame"], after["frame"], after["life"], labels) if frame and "frame" in changed else None
    return (None, why) if why else (restarts, None)


def declared(patches, before, after, changed, frame, role):
    """The restarts of `verdict`, or None."""
    return verdict(patches, before, after, changed, frame, role)[0]
