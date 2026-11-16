"""A fake probe for the U05e tests (state-scoped taps, the layer policy of the tap judges, the pad's digit map, boot
seeds, prefixes, the run-time budget): speaks ui-probe/1 with frame facts for a 320 x 240 scene in the judges'
vocabulary (docs/ui-judges.md), and LVGL's pointer search (the last clickable node in walk order that holds the point).

The base screen: button `go` (10,10 100x40, intent 1:0) adds 1 to the count; button `off` (120,10 100x40) is disabled
(D, no intent); text `count` shows "N=<n>"; pad keys `k1`, `k2` (10,60 / 60,60, 40x30, intents 5:0 and 5:1 when
mapped, else 5:<digit>) type a digit, `ok` (110,60 40x30, 6:0) clears the entry and adds 10 to the count. One overlay
per mode is shown at `open` (or after `apply 3 9 0`):

    plain        no overlay
    slow         no overlay; every `open` takes 0.4 s of wall time (the run-time budget)
    dialog       a modal dialog: scrim 0,0 320x240 (clickable, opacity 82, no intent), card 60,60 200x120, its Close
                 button 110,60 100x30 (2:0, drawn over the key `ok`); the card is clickable (over the key `k2`); a tap
                 on the scrim or the card does nothing (correct)
    dialoglive   as dialog, but a tap on the scrim over `go` still adds 1 (blocked-target-live)
    snack        a snackbar: scrim 0,0 320x240 (clickable, opacity 0, intent 3:0), card 20,180 280x50, its OK button
                 200,190 80x30 (3:0); a tap on the scrim dismisses it (correct: tap outside dismisses)
    snackbad     as snack, but a tap on the scrim does nothing (tap-misrouted: the dismiss was expected)
    snackmore    as snack, but a tap on the scrim also adds 1 (tap-misrouted)
    banner       a pass-through banner: scrim 0,0 320x240 (clickable, opacity 0, intent 4:0), card 0,200 320x40; a tap
                 on the scrim removes only the banner (tap-swallowed-first over `go`)
    keyed        no overlay; the pad's digit keys take `apply 3 <key intent> <arg>` with intents 5:0 / 5:1 only (a
                 digit map), and `apply 3 5 <d>` for another digit is refused
    seeded       no overlay; the seed of `open` is shown as the count (boot seeds)

In every mode `apply 3 1 0` is `go` (`ok apply missed` while a dialog shows), `apply 3 9 0` shows the mode's overlay
again, `apply 2 0 0 <hex>` (a wedge line) is refused. Trace types: go, digit, enter, close, dismiss, show.
"""

import os
import sys
import time

MODE = sys.argv[1]
OVERLAY = {"dialog": "dialog", "dialoglive": "dialog", "snack": "snack", "snackbad": "snack", "snackmore": "snack",
           "banner": "banner"}.get(MODE)
W, H = 320, 240


class Model:
    def __init__(self, origin, seed):
        self.now, self.count, self.entry, self.overlay = origin, seed if MODE == "seeded" else 0, "", OVERLAY
        self.trace, self.patches, self.seq = [], [], 0
        self.event("boot")

    def event(self, kind):
        self.trace.append("%d\t%s\t%d" % (self.seq, kind, self.now))
        self.seq += 1

    def text(self):
        return "N=%d E=%s" % (self.count, self.entry)

    def change(self, kind, by=0, entry=None):
        old = self.text()
        self.count += by
        self.entry = self.entry if entry is None else entry
        self.patches.append("update\tcount\ttext\t%s\t%s" % (old, self.text()))
        self.event(kind)

    def close(self, kind):
        self.patches.append("delete\t%s\t-\t-\t-" % self.overlay)
        self.overlay = None
        self.event(kind)


def sem(key, role, label, rect, intent="-", flags="-", style=0, enabled=1):
    return "\t".join([key, role, label] + [str(v) for v in rect] + [str(enabled), intent, flags, str(style), "-", "-",
                                                                     "-"])


def scene(model):
    """(semantic records, rendered nodes): a node is (parent, class, box x1 y1 x2 y2, clickable, bg opa, label)."""
    digit = (lambda d: "5:%d" % d) if MODE != "keyed" else (lambda d: "5:%d" % (d - 1))
    records = [sem("root", "root", "", (0, 0, W, H)), sem("go", "button", "Go", (10, 10, 100, 40), "1:0", style=5),
               sem("off", "button", "Off", (120, 10, 100, 40), "-", "D", 5, 0),
               sem("count", "text", model.text(), (10, 100, 100, 20), style=2),
               sem("k1", "key", "1", (10, 60, 40, 30), digit(1), style=5), sem("k2", "key", "2", (60, 60, 40, 30),
                                                                                 digit(2), style=5),
               sem("ok", "key", "OK", (110, 60, 40, 30), "6:0", style=5)]
    nodes = [(-1, "lv_obj", (0, 0, W - 1, H - 1), 1, 255, None), (0, "lv_button", (10, 10, 109, 49), 1, 255, None),
             (1, "lv_label", (40, 20, 79, 39), 0, 0, "Go"), (0, "lv_button", (120, 10, 219, 49), 1, 255, None),
             (3, "lv_label", (150, 20, 189, 39), 0, 0, "Off"), (0, "lv_label", (10, 100, 109, 119), 0, 0,
                                                                 model.text())]
    for key, label, x in (("k1", "1", 10), ("k2", "2", 60), ("ok", "OK", 110)):
        parent = len(nodes)
        nodes += [(0, "lv_button", (x, 60, x + 39, 89), 1, 255, None), (parent, "lv_label", (x + 5, 65, x + 34, 84),
                                                                         0, 0, label)]
    overlay(model, records, nodes)
    return records, nodes


def overlay(model, records, nodes):
    if model.overlay == "dialog":
        records += [sem("dscrim", "scrim", "", (0, 0, W, H)), sem("dcard", "dialog", "", (60, 60, 200, 120)),
                    sem("dclose", "button", "Close", (110, 60, 100, 30), "2:0", style=5)]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 82, None), (len(nodes), "lv_obj", (60, 60, 259, 179), 1,
                                                                         255, None)]
        nodes += [(len(nodes) - 1, "lv_button", (110, 60, 209, 89), 1, 255, None),
                  (len(nodes), "lv_label", (130, 65, 189, 84), 0, 0, "Close")]
    elif model.overlay == "snack":
        records += [sem("sscrim", "scrim", "", (0, 0, W, H), "3:0"), sem("scard", "snackbar", "", (20, 180, 280, 50)),
                    sem("sok", "button", "OK", (200, 190, 80, 30), "3:0", style=5)]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 0, None), (len(nodes), "lv_obj", (20, 180, 299, 229), 0,
                                                                        255, None)]
        nodes += [(len(nodes) - 1, "lv_button", (200, 190, 279, 219), 1, 255, None),
                  (len(nodes), "lv_label", (220, 195, 259, 214), 0, 0, "OK")]
    elif model.overlay == "banner":
        records += [sem("bscrim", "scrim", "", (0, 0, W, H), "4:0"), sem("bcard", "banner", "", (0, 200, W, 40))]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 0, None), (len(nodes), "lv_obj", (0, 200, W - 1, 239), 0,
                                                                        255, None)]


def frame(model):
    _, nodes = scene(model)
    depth, out = [], ["lvprobe\t1\t%d" % len(nodes), "frame\t%d\t%d\t%08x" % (W, H, model.count + len(nodes))]
    for index, (parent, cls, box, click, opa, label) in enumerate(nodes):
        depth.append(0 if parent == -1 else depth[parent] + 1)
        out.append("\t".join(["node", str(index), str(parent), str(depth[index]), cls] + [str(v) for v in box]
                             + ["0", str(click), "-1", "-1", "0", "0", "ffffff", str(opa), str(opa), "1", "0", "0"]))
        if label is not None:
            w, h = box[2] - box[0] + 1, box[3] - box[1] + 1
            out.append("\t".join(["label", str(index), "-", "16", "0", "1", "0", "0", "1", str(w), str(h), str(w),
                                  str(h), "=" + label, "-"]))
        out.append("region\t%d\t%08x" % (index, index))
    return out


def hit(model, x, y):
    """LVGL's search: the last clickable node in walk order whose box holds the point."""
    _, nodes = scene(model)
    found = [i for i, (_, _, b, click, _, _) in enumerate(nodes) if click and b[0] <= x <= b[2] and b[1] <= y <= b[3]]
    return found[-1] if found else 0


PAD = {(10, 60, 49, 89): "1", (60, 60, 99, 89): "2"}


def tap(model, x, y):
    """A press and release at (x, y): the pressed node's effect; returns the pressed walk index."""
    _, nodes = scene(model)
    index = hit(model, x, y)
    box = nodes[index][2]
    on_go = 10 <= x <= 109 and 10 <= y <= 49
    if index == 0:
        return index
    if box == (10, 10, 109, 49):
        model.change("go", 1)
    elif box in PAD:
        model.change("digit", entry=model.entry + PAD[box])
    elif box == (110, 60, 149, 89) and model.entry:
        model.change("enter", 10, "")
    elif box in ((110, 60, 209, 89), (200, 190, 279, 219)):
        model.close("close")
    elif box == (0, 0, W - 1, H - 1):
        scrim(model, on_go)
    return index


def scrim(model, on_go):
    if MODE == "dialoglive" and on_go:
        model.change("go", 1)
    elif MODE in ("snack", "snackmore", "banner"):
        model.close("dismiss")
        if MODE == "snackmore":
            model.change("go", 1)


def apply(model, kind, ident, arg):
    blocked = model.overlay == "dialog"
    if kind != 3:
        return "ok apply refused"
    if ident in (1, 5, 6) and blocked:
        return "ok apply missed"
    if ident == 1:
        model.change("go", 1)
    elif ident == 5 and (arg in (0, 1) if MODE == "keyed" else 0 <= arg <= 9):
        model.change("digit", entry=model.entry + str(arg + 1 if MODE == "keyed" else arg))
    elif ident == 6 and model.entry:
        model.change("enter", 10, "")
    elif (ident, model.overlay) in ((2, "dialog"), (3, "snack"), (4, "banner")):
        model.close("close")
    elif ident == 9 and model.overlay is None and OVERLAY is not None:
        model.overlay = OVERLAY
        model.patches.append("create\t%s\t-\t-\t-" % OVERLAY)
        model.event("show")
    else:
        return "ok apply refused"
    return "ok apply"


def say(lines):
    sys.stdout.write("".join(line + "\n" for line in lines))
    sys.stdout.flush()


def logs(model, name):
    items = model.patches if name == "patches" else model.trace
    if name == "patches":
        model.patches = []
    else:
        model.trace = []
    return ["ok %s lines %d" % (name, len(items))] + items


def handle(words, model):
    cmd = words[0]
    if cmd == "open":
        if MODE == "slow":
            time.sleep(0.4)
        return Model(int(words[1]), int(words[2])), ["ok open"]
    if cmd == "apply":
        return model, [apply(model, int(words[1]), int(words[2]), int(words[3]))]
    if cmd in ("patches", "trace"):
        return model, logs(model, cmd)
    if cmd == "advance":
        model.now = int(words[1])
        return model, ["ok advance %d" % model.now]
    if cmd == "tap":
        index = tap(model, int(words[1]), int(words[2]))
        return model, ["ok tap %d %d" % (index, index)]
    if cmd == "crop":
        return model, ["ok crop lines %d" % int(words[4])] + ["ffffffff" * int(words[3])] * int(words[4])
    replies = {"domain-count": lambda: ["ok domain-count 0"], "next-due": lambda: ["ok next-due none"],
               "env-inputs": lambda: ["ok env-inputs 0"],
               "hit-test": lambda: ["ok hit-test %d" % hit(model, int(words[1]), int(words[2]))],
               "semantic": lambda: ["ok semantic lines %d" % len(scene(model)[0])] + scene(model)[0],
               "frame": lambda: ["ok frame lines %d" % len(frame(model))] + frame(model)}
    return model, replies.get(cmd, lambda: ["err ? unknown-command"])()


def main():
    say(["ui-probe/1 ready frame-facts hit-test tap apply-missed crop"])
    model = None
    for raw in sys.stdin:
        words = raw.rstrip("\n").split(" ")
        if words[0] == "quit":
            say(["ok quit"])
            return 0
        model, replies = handle(words, model)
        say(replies)
    return 1


if __name__ == "__main__":
    sys.exit(main())
