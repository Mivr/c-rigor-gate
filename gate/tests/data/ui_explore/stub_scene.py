"""A fake probe for the U05e tests (state-scoped taps, the layer policy of the tap judges, the pad's digit map, boot
seeds, prefixes, the run-time budget): speaks ui-probe/1 with frame facts for a 320 x 240 scene in the judges'
vocabulary (docs/ui-judges.md), and LVGL's pointer search (the last clickable node in walk order that holds the point).

The base screen: button `go` (10,10 100x40, intent 1:0) adds 1 to the count; button `off` (120,10 100x40) is disabled
(D, no intent); text `count` shows "N=<n>"; pad keys `51` (the key "1", so `apply 3 51 0` names it by key) and `k2`
(10,60 / 60,60, 40x30, intents 5:0 and 5:1 when mapped, else 5:<digit>) type a digit, `ok` (110,60 40x30, 6:0)
clears the entry and adds 10 to the count. One overlay per mode is shown at `open` (or after `apply 3 9 0`); closing
an overlay patches `delete <its scrim key>` and posts `close` (its own button, its intent) or `dismiss` (its scrim):

    plain        no overlay
    slow         no overlay; every `open` takes 0.1 s of wall time (the run-time budget)
    dialog       a modal dialog: scrim 0,0 320x240 (clickable, opacity 82, no intent), card 60,60 200x120, its Close
                 button 110,60 100x30 (2:0, drawn over the key `ok`); the card is clickable (over the key `k2`); a tap
                 on the scrim or the card does nothing (correct)
    dialoglive   as dialog, but a tap on the scrim over `go`, and `apply 3 1 0`, still add 1 (blocked-target-live), and
                 its Close adds 1 as well as closing
    dialogdup    as dialog, but its Close publishes go's intent 1:0 (a live control sharing an inert node's intent)
    snack        a snackbar: scrim 0,0 320x240 (clickable, opacity 0, intent 3:0), card 20,180 280x50, its OK button
                 200,190 80x30 (3:0); a tap on the scrim dismisses it (correct: tap outside dismisses)
    snackbad     as snack, but a tap on the scrim does nothing (tap-misrouted: the dismiss was expected)
    snackmore    as snack, but a tap on the scrim also adds 1 (tap-misrouted)
    snacktwice   as snack, but the dismiss also posts a second trace event `beep` (tap-misrouted)
    snackdue     as snack, but the dismiss also arms a deadline 500 ms later (tap-misrouted)
    snackmodal   as snack, with its scrim dimmed (opacity 82): with a contract whose snackbar blocks input below, the
                 targets under it are inert, and a tap outside the card that dismisses is `dismissed`
    snackfull    as snack (with identity), but closing the snackbar, by its scrim or by `apply 3 3 0`, posts `close` and also adds 1 (more
                 than the layer leaving, and exactly what its own intent does)
    snackcleared as snack (with identity), but closing it, by its scrim or by `apply 3 3 0`, posts `close` and
                 `cleared` (two trace events: only the layer leaves, as on the kiosk)
    snacknoop    as snack, with scene identity (`identity`: its OK button `sok` is the `dismiss` element): a tap on the
                 scrim does nothing and the bound dismiss intent 3:0 is refused (no sibling)
    snackstay    as snacknoop, but `apply 3 3 0` is accepted and changes nothing (the sibling leaves the layer)
    snackopen    as snack, with identity, but the scrim carries an unrelated intent 7:0 ("open"): a tap on the scrim,
                 and `apply 3 7 0`, add 100 and keep the snackbar; `apply 3 3 0` (the bound dismiss) closes it
    snacktag     as snack, with identity, but its OK button (the `dismiss` element) and the scrim carry 7:0, which closes
                 the snackbar AND adds 100: a "dismiss" that does more than the layer leaving
    snackkeys    as snack, with identity, its scrim, card and OK keyed 60, 61, 62 (intent_node "key"): `apply 3 60 0`
                 adds 100 and keeps the snackbar, `apply 3 62 0` (the bound dismiss) and a tap on the scrim close it
                 (trace `close`)
    snackdead    as snack, with identity, but its OK button (the `dismiss` element) is disabled (D, enabled 0; it still
                 publishes 3:0, which `apply 3 3 0` would close with trace `close`)
    stack        as snack, with identity, over a pass-through banner (both shown at open); a tap on the snackbar's scrim
                 closes the snackbar only
    stackwrong   as stack, but a tap on the snackbar's scrim closes the banner instead
    snackcount   as snack, and the product's pointer entry (`pointer`): every tap posts `touch`, and the first tap
                 restarts a countdown `cd` ("298 s" -> "300 s"); the dismiss is still exactly the snackbar's
    banner       a pass-through banner: scrim 0,0 320x240 (clickable, opacity 0, intent 4:0), card 0,200 320x40; a tap
                 on the scrim removes only the banner (tap-swallowed-first over `go`)
    bannerok     as banner, but a tap on the scrim over `go` also presses `go` (the control below acts)
    keyed        no overlay; the pad's digit keys take `apply 3 <key intent> <arg>` with intents 5:0 / 5:1 only (a
                 digit map), and `apply 3 5 <d>` for another digit is refused
    seeded       no overlay; the seed of `open` is shown as the count (boot seeds)
    badtree      no overlay; the frame's node 2 claims depth 5 (its records parse, its tree does not)
    half         no overlay; `ok`'s scene rect is one pixel right of its box (no association), a button `dup` (8:0) is
                 published twice and a button `hid` (8:1) is flagged H: some controls are tapped, `ok` and `dup` not
    unassoc      no overlay; the scene rects of go, 51, k2 and ok are one pixel right of their rendered boxes (no
                 association), and a button `dup` (8:0) is published twice: no control can be tapped

With UI_STUB_READY set, the stub creates that file at its first `open` (a test's "the run is underway").

In every mode `apply 3 1 0` is `go` (`ok apply missed` while a dialog shows), `apply 3 9 0` shows the mode's overlay
again, `apply 2 0 0 <hex>` (a wedge line) is refused. Trace types: go, digit, enter, close, dismiss, show.
"""

import os
import sys
import time

MODE = sys.argv[1]
IDENTITY = ("snackfull", "snackcleared", "snacknoop", "snackstay", "snackopen", "snacktag", "snackkeys", "snackdead", "stack",
            "stackwrong")
KEYS = ("60", "61", "62") if MODE == "snackkeys" else ("sscrim", "scard", "sok")
SNACKS = ("snack", "snackbad", "snackmore", "snacktwice", "snackdue", "snackmodal", "snackcount") + IDENTITY
OVERLAY = dict([(m, "snack") for m in SNACKS], dialog="dialog", dialoglive="dialog", dialogdup="dialog",
               banner="banner", bannerok="banner").get(MODE)
SCRIMS = {"dialog": "dscrim", "snack": KEYS[0], "banner": "bscrim"}
W, H = 320, 240


class Model:
    def __init__(self, origin, seed):
        self.now, self.count, self.entry, self.overlay = origin, seed if MODE == "seeded" else 0, "", OVERLAY
        self.trace, self.patches, self.seq, self.due = [], [], 0, None
        self.cd = 298 if MODE == "snackcount" else None
        self.banner = MODE in ("stack", "stackwrong")      # a second layer under the snackbar
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
        self.patches.append("delete\t%s\t-\t-\t-" % SCRIMS[self.overlay])
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
               sem("51", "key", "1", (10, 60, 40, 30), digit(1), style=5), sem("k2", "key", "2", (60, 60, 40, 30),
                                                                                 digit(2), style=5),
               sem("ok", "key", "OK", (110, 60, 40, 30), "6:0", style=5)]
    if model.cd is not None:
        records.append(sem("cd", "countdown", "%d s" % model.cd, (200, 100, 100, 20), style=2))
    nodes = [(-1, "lv_obj", (0, 0, W - 1, H - 1), 1, 255, None), (0, "lv_button", (10, 10, 109, 49), 1, 255, None),
             (1, "lv_label", (40, 20, 79, 39), 0, 0, "Go"), (0, "lv_button", (120, 10, 219, 49), 1, 255, None),
             (3, "lv_label", (150, 20, 189, 39), 0, 0, "Off"), (0, "lv_label", (10, 100, 109, 119), 0, 0,
                                                                 model.text())]
    for key, label, x in (("51", "1", 10), ("k2", "2", 60), ("ok", "OK", 110)):
        parent = len(nodes)
        nodes += [(0, "lv_button", (x, 60, x + 39, 89), 1, 255, None), (parent, "lv_label", (x + 5, 65, x + 34, 84),
                                                                         0, 0, label)]
    if model.cd is not None:
        nodes.append((0, "lv_label", (200, 100, 299, 119), 0, 0, "%d s" % model.cd))
    overlay(model, records, nodes)
    if MODE == "half":
        records = [line.replace("ok\tkey\tOK\t110\t", "ok\tkey\tOK\t111\t") for line in records]
        records += [sem("dup", "button", "Dup", (200, 60, 40, 30), "8:0", style=5)] * 2
        records += [sem("hid", "button", "Hid", (200, 120, 40, 30), "8:1", "H", style=5)]
    if MODE == "unassoc":
        moved = []
        for line in records:
            fields = line.split("\t")
            if fields[0] in ("go", "51", "k2", "ok"):
                fields[3] = str(int(fields[3]) + 1)
            moved.append("\t".join(fields))
        records = moved + [sem("dup", "button", "Dup", (200, 60, 40, 30), "8:0", style=5)] * 2
    return records, nodes


def overlay(model, records, nodes):
    if model.overlay == "dialog":
        records += [sem("dscrim", "scrim", "", (0, 0, W, H)), sem("dcard", "dialog", "", (60, 60, 200, 120)),
                    sem("dclose", "button", "Close", (110, 60, 100, 30), "1:0" if MODE == "dialogdup" else "2:0",
                        style=5)]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 82, None), (len(nodes), "lv_obj", (60, 60, 259, 179), 1,
                                                                         255, None)]
        nodes += [(len(nodes) - 1, "lv_button", (110, 60, 209, 89), 1, 255, None),
                  (len(nodes), "lv_label", (130, 65, 189, 84), 0, 0, "Close")]
    if model.banner:
        records += [sem("bscrim", "scrim", "", (0, 0, W, H), "4:0"), sem("bcard", "banner", "", (0, 200, W, 40))]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 0, None), (len(nodes), "lv_obj", (0, 200, W - 1, 239), 0,
                                                                        255, None)]
    if model.overlay == "snack":
        ok = ("3:0", "D", 0) if MODE == "snackdead" else ("7:0" if MODE == "snacktag" else "3:0", "-", 1)
        records += [sem(KEYS[0], "scrim", "", (0, 0, W, H), "7:0" if MODE in ("snackopen", "snacktag") else "3:0"),
                    sem(KEYS[1], "snackbar", "", (20, 180, 280, 50)),
                    sem(KEYS[2], "button", "OK", (200, 190, 80, 30), ok[0], ok[1], 5, ok[2])]
        nodes += [(0, "lv_obj", (0, 0, W - 1, H - 1), 1, 82 if MODE == "snackmodal" else 0, None),
                  (len(nodes), "lv_obj", (20, 180, 299, 229), 0, 255, None)]
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
        shown = 5 if MODE == "badtree" and index == 2 else depth[index]
        out.append("\t".join(["node", str(index), str(parent), str(shown), cls] + [str(v) for v in box]
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
    if MODE == "snackcount":
        model.event("touch")                        # the pointer entry's own event, at the tap's instant
        if model.cd == 298:
            model.patches.append("update\tcd\ttext\t298 s\t300 s")
            model.cd = 300
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
        if MODE == "dialoglive":           # its Close also presses go: not only its own dismiss
            model.change("go", 1)
    elif box == (0, 0, W - 1, H - 1):
        scrim(model, on_go)
    return index


def scrim(model, on_go):
    if MODE == "dialoglive" and on_go:
        model.change("go", 1)
    elif MODE == "snackfull":
        model.close("close")
        model.change("go", 1)
    elif MODE == "snackcleared":
        model.close("close")
        model.event("cleared")
    elif MODE == "snackopen":
        model.change("open", 100)
    elif MODE == "snacktag":
        model.close("close")
        model.change("open", 100)
    elif MODE == "snackkeys":
        model.close("close")
    elif MODE == "stackwrong":
        model.banner = False
        model.patches.append("delete\tbscrim\t-\t-\t-")
        model.event("dismiss")
    elif MODE in ("snacknoop", "snackstay"):
        pass
    elif MODE in SNACKS + ("banner", "bannerok") and MODE != "snackbad":
        model.close("dismiss")
        if MODE == "snackmore" or MODE == "bannerok" and on_go:
            model.change("go", 1)
        if MODE == "snacktwice":
            model.event("beep")
        if MODE == "snackdue":
            model.due = model.now + 500


def apply(model, kind, ident, arg):
    blocked = model.overlay == "dialog"
    if kind != 3:
        return "ok apply refused"
    if ident in (1, 5, 6, 51) and blocked and not (MODE == "dialoglive" and ident == 1):
        return "ok apply missed"
    if ident == 3 and MODE == "snacknoop":
        return "ok apply refused"
    if ident == 3 and MODE == "snackstay":
        return "ok apply"
    if ident == 7 and MODE == "snacktag" and model.overlay == "snack":
        model.close("close")
        model.change("open", 100)
        return "ok apply"
    if ident in (60, 62) and MODE == "snackkeys" and model.overlay == "snack":
        model.change("open", 100) if ident == 60 else model.close("close")
        return "ok apply"
    if ident == 7 and MODE == "snackopen":
        model.change("open", 100)
        return "ok apply"
    if ident == 51 and arg == 0:
        model.change("digit", entry=model.entry + "1")
    elif ident == 1:
        model.change("go", 1)
    elif ident == 5 and (arg in (0, 1) if MODE == "keyed" else 0 <= arg <= 9):
        model.change("digit", entry=model.entry + str(arg + 1 if MODE == "keyed" else arg))
    elif ident == 6 and model.entry:
        model.change("enter", 10, "")
    elif (ident, model.overlay) in ((2, "dialog"), (3, "snack"), (4, "banner")):
        model.close("close")
        if MODE == "snackfull":
            model.change("go", 1)
        if MODE == "snackcleared":
            model.event("cleared")
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
            time.sleep(0.1)
        if os.environ.get("UI_STUB_READY") and not os.path.exists(os.environ["UI_STUB_READY"]):
            open(os.environ["UI_STUB_READY"], "w").close()
        return Model(int(words[1]), int(words[2])), ["ok open"]
    if cmd == "apply":
        return model, [apply(model, int(words[1]), int(words[2]), int(words[3]))]
    if cmd in ("patches", "trace"):
        return model, logs(model, cmd)
    if cmd == "advance":
        model.now = int(words[1])
        model.due = None if model.due is not None and model.now >= model.due else model.due
        return model, ["ok advance %d" % model.now]
    if cmd == "tap":
        index = tap(model, int(words[1]), int(words[2]))
        return model, ["ok tap %d %d" % (index, index)]
    if cmd == "crop":
        return model, ["ok crop lines %d" % int(words[4])] + ["ffffffff" * int(words[3])] * int(words[4])
    if cmd == "identity":
        dismiss = ["node\t%s\tdismiss\t-\t0" % KEYS[2]] if model.overlay == "snack" else []
        return model, ["ok identity lines %d" % (1 + len(dismiss)), "state\tmain"] + dismiss
    replies = {"domain-count": lambda: ["ok domain-count 0"],
               "next-due": lambda: ["ok next-due " + ("none" if model.due is None else str(model.due))],
               "env-inputs": lambda: ["ok env-inputs 0"],
               "hit-test": lambda: ["ok hit-test %d" % hit(model, int(words[1]), int(words[2]))],
               "semantic": lambda: ["ok semantic lines %d" % len(scene(model)[0])] + scene(model)[0],
               "frame": lambda: ["ok frame lines %d" % len(frame(model))] + frame(model)}
    return model, replies.get(cmd, lambda: ["err ? unknown-command"])()


def main():
    say(["ui-probe/1 ready frame-facts hit-test tap apply-missed crop" + (" pointer" if MODE == "snackcount" else "")
         + (" identity" if MODE in IDENTITY else "")])
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
