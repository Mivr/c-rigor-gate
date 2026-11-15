"""A fake probe for the ui-explore unit tests: speaks ui-probe/1 for a toy model (a button, a timed notice, wedge lines
accepted when not empty), and misbehaves on purpose in the mode named by argv[1]. With UI_STUB_LOG set, every command
line is appended to that file (the tests read the advances), and the probe's pid is written to UI_STUB_LOG + ".pid".

    good         deterministic
    nondet       the press event's trace type carries the process id (model-nondeterministic)
    mismatch     after a press the notice label and the notice deadline carry the process id (run-twice-mismatch:
                 the label is read before the deadline)
    starve       a press arms a timer that re-arms itself 1 ms later on every firing (timer-starvation)
    tick         a perpetual 250 ms tick from boot that changes nothing visible (correct; no finding)
    far          a press arms a deadline 2^40 ms away (timer-unreachable)
    beyond       a press arms a deadline past the protocol's 2^52 clock limit (timer-unreachable)
    huge         a press arms a deadline at 2^64 - 2, the largest the C probe can print (timer-unreachable)
    longline     a semantic record line of 70 000 bytes
    duenow       after a press `next-due` replies the current time (zero-delay)
    duenowerr    after a press `next-due` replies `err next-due model-contract` (zero-delay)
    exit         exits without a reply at the first `apply`
    orphan       starts a grandchild that holds stdout, then exits at the first `apply`
    malformed    replies to `semantic` with a record of the wrong field count
    hang         never replies to `apply`
    errreply     replies `err apply bad-arguments` to `apply`
    extra        writes one line nobody asked for after the reply to the first `apply`
    quitgarbage  writes a line after `ok quit`
    quitexit1    exits with status 1 after `ok quit`
    failnext     replies `fail next-due` (a command that never fails)
    bigid        an env input whose id has 5000 digits
    bigdomain    domain-count 70000
    bigreply     a semantic reply of more than 65536 payload bytes
    refusechange a refused apply still emits a trace event
    refuseall    refuses every apply
    tapcap       announces hit-test and tap; `hit-test x y` finds nothing, `tap x y` presses nothing
    badcap       announces an unknown capability
    framelines   replies to `frame` with two escaped seam lines
    nodomain     domain-count 0
    alt          a press arms a timer that re-arms itself alternately 1 ms and 17 ms later (near-starvation)
    refuseframe  a refused apply changes the frame lines (and nothing else)
    padenter     the pad's enter is always refused (digits accepted)
    paddigit     a refused pad digit (9) still emits a patch
    capflip      announces tap on odd launches only (needs UI_STUB_LOG for the launch count)
    nogreet      never writes its greeting
    extraframe   writes a look-alike `ok frame lines 0` after the reply to the first `apply`
    missed       announces apply-missed; a press while the notice is shown is `ok apply missed`
    badorder     announces `tap hit-test` (out of the documented order)
    dupcap       announces `tap tap`

The frame-facts modes announce every capability (`frame-facts ink hit-test tap apply-missed crop`, as the C probe does)
and model a 4x2 display: walk node 0 the screen, node 1 a 2x2 button at (0, 0) whose tap presses like intent 1; while
the notice is shown the button's tap changes nothing (the F3b canary) and intent 1 is `ok apply missed`:

    facts        correct frame records, hit-test, tap, crop and ink
    framebad     the button's `node` record has 20 fields
    frametype    the frame has a record of an unknown type
    tapblocked   `hit-test` and `tap` reply blocked
    tapdisagree  `tap` presses the screen where `hit-test` found the button
    noframe      `hit-test` replies `err hit-test no-frame`
    toolarge     `frame` replies `err frame too-large`
    blankchange  a tap on the screen (outside the button) emits a trace event
    cropbad      `crop` rows are one hex digit short

In every mode intent 2 is accepted only while the notice is shown (trace `late`), intent 10 is a pad digit (accepted,
trace `digit`) and intent 11 the pad's enter (accepted after a digit, trace `enter`). A stub that would sleep exits as
soon as its parent is gone, so a killed explorer never leaves one behind.
"""

import os
import subprocess
import sys
import time

MODE = sys.argv[1]
NOTICE_MS = 3000
FACTS = ("facts", "framebad", "frametype", "tapblocked", "tapdisagree", "noframe", "toolarge", "blankchange", "cropbad")
SCREEN = "node\t0\t-1\t0\tlv_obj\t0\t0\t3\t1\t0\t1\t-1\t-1\t0\t0\tffffff\t255\t255\t1\t0\t0"
BUTTON = "node\t1\t0\t1\tlv_button\t0\t0\t1\t1\t0\t1\t-1\t-1\t0\t0\t2196f3\t255\t255\t1\t0\t0"
FACT_FRAME = ["lvprobe\t1\t2", "frame\t4\t2\t0badcafe", SCREEN, "region\t0\t0badcafe", BUTTON, "region\t1\t12345678",
              "life\t0\tcreated\t0\t-1\t0\tlv_\\x01obj"]
LOG = os.environ.get("UI_STUB_LOG")


class Model:
    def __init__(self, origin):
        self.now = origin
        self.notice = ""
        self.due = None
        self.spin = None
        self.tick = origin + 250 if MODE == "tick" else None
        self.pad, self.digit = "", 0
        self.frames = []
        self.alt = 1
        self.zero = False
        self.seq = 0
        self.trace = []
        self.patches = ["create\tscreen\t-\t-\t-"]
        self.event("boot")

    def event(self, kind):
        self.trace.append("%d\t%s\t%d" % (self.seq, kind, self.now))
        self.seq += 1

    def next_due(self):
        dues = [d for d in (self.due, self.spin, self.tick) if d is not None]
        return min(dues) if dues else None

    def press(self):
        self.notice = "Pressed" + (str(os.getpid()) if MODE == "mismatch" else "")
        self.due = self.now + NOTICE_MS + (os.getpid() if MODE == "mismatch" else 0)
        self.due = {"far": self.now + (1 << 40), "beyond": (1 << 53), "huge": 2**64 - 2}.get(MODE, self.due)
        self.spin = self.now + 1 if MODE in ("starve", "alt") else None
        self.zero = MODE in ("duenow", "duenowerr")
        self.patches.append("set\tnotice\thidden\t1\t0")
        self.event("press-%d" % os.getpid() if MODE == "nondet" else "press")

    def apply(self, kind, ident, text):
        if MODE == "refuseall":
            return "ok apply refused"
        if kind == 3 and ident == 2 and self.notice:
            self.event("late")
            return "ok apply"
        if kind == 3 and ident == 10 and not (MODE == "paddigit" and text == "-" and self.digit == 9):
            self.pad += str(self.digit)
            self.event("digit")
            return "ok apply"
        if kind == 3 and ident == 10:
            self.patches.append("set\tpad\ttext\t-\t9")
            return "ok apply refused"
        if kind == 3 and ident == 11 and self.pad and MODE != "padenter":
            self.pad = ""
            self.event("enter")
            return "ok apply"
        if kind == 3 and ident == 1 and self.notice and (MODE == "missed" or MODE in FACTS):
            return "ok apply missed"
        if kind == 3 and ident == 1 and not self.notice:
            self.press()
            return "ok apply"
        if kind == 1 and ident == 1 and not self.notice:
            self.notice, self.due = "Offline", self.now + NOTICE_MS
            self.event("env_offline")
            return "ok apply"
        if kind == 2 and text != "-":
            self.event("line")
            return "ok apply"
        if MODE == "refusechange":
            self.event("refused-but-changed")
        if MODE == "refuseframe":
            self.frames = ["refused\t%d" % (len(self.frames) + 1)]
        return "ok apply refused"

    def advance(self, to):
        while self.now < to:
            due = self.next_due()
            self.now = min(to, due) if due is not None else to
            if self.spin is not None and self.now >= self.spin:
                self.alt = 18 - self.alt if MODE == "alt" else 1
                self.spin = self.now + self.alt
            if self.tick is not None and self.now >= self.tick:
                self.tick += 250
            if self.due is not None and self.now >= self.due:
                self.notice, self.due = "", None
                self.patches.append("set\tnotice\thidden\t0\t1")
                self.event("notice_timeout")

    def semantic(self):
        flags = "-" if self.notice else "hidden"
        return ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
                "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
                "notice\tlabel\t%s\t8\t90\t%d\t16\t1\t-\t%s\tbody\tnormal\tnone\tnone" % (self.notice, 8 * len(self.notice), flags)]


def say(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def lines(name, items):
    say("ok %s lines %d" % (name, len(items)))
    for item in items:
        say(item)


def next_due(model):
    if model.zero and MODE == "duenowerr":
        return "err next-due model-contract"
    if model.zero:
        return "ok next-due %d" % model.now
    due = model.next_due()
    return "ok next-due none" if due is None else "ok next-due %d" % due


def special(cmd, model, state):
    """Replies of the misbehaving modes; None when the mode does not touch this command."""
    if cmd == "apply" and MODE in ("exit", "orphan"):
        if MODE == "orphan":
            child = subprocess.Popen(["sleep", "30"])
            if LOG:
                with open(LOG + ".orphan", "w") as stream:
                    stream.write(str(child.pid))
        sys.exit(3)
    if cmd == "apply" and MODE == "hang":
        linger()
    if cmd == "apply" and MODE == "errreply":
        return ["err apply bad-arguments"]
    if cmd == "next-due" and MODE == "failnext":
        return ["fail next-due"]
    if cmd == "env-inputs" and MODE == "bigid":
        return ["ok env-inputs 1 1:%s:0:-" % ("9" * 5000)]
    if cmd == "domain-count" and MODE in ("bigdomain", "nodomain"):
        return ["ok domain-count %d" % (70000 if MODE == "bigdomain" else 0)]
    if cmd == "semantic" and MODE == "bigreply":
        return ["ok semantic lines 2"] + ["k\tr\t%s\t0\t0\t0\t0\t1\t-\t-\ts\ti\tp\tw" % ("x" * 40000)] * 2
    if cmd == "semantic" and MODE == "longline":
        return ["ok semantic lines 1", "k\tr\t%s\t0\t0\t0\t0\t1\t-\t-\ts\ti\tp\tw" % ("x" * 70000)]
    if cmd == "semantic" and MODE == "malformed":
        return ["ok semantic lines 1", "title\tlabel"]
    if cmd == "frame" and MODE == "framelines":
        return ["ok frame lines 2", "obj\tlabel\tA\\tB", "crc\t\\x01ff"]
    if cmd == "apply" and MODE in ("extra", "extraframe") and not state.get("extra"):
        state["extra"] = True
        return [model.apply(3, 1, "-"), "stray output" if MODE == "extra" else "ok frame lines 0"]
    return None


def fact_frame():
    frame = list(FACT_FRAME)
    if MODE == "framebad":
        frame[4] = BUTTON.rsplit("\t", 1)[0]
    if MODE == "frametype":
        frame.append("bogus\t1")
    return frame


def facts(words, model):
    """Replies of the frame-facts modes to frame, hit-test, tap, crop and ink; None for every other command."""
    cmd = words[0]
    if cmd == "frame":
        return ["err frame too-large"] if MODE == "toolarge" else ["ok frame lines %d" % len(fact_frame())] + fact_frame()
    if cmd == "hit-test":
        if MODE in ("tapblocked", "noframe"):
            return ["ok hit-test blocked" if MODE == "tapblocked" else "err hit-test no-frame"]
        return ["ok hit-test %d" % (1 if int(words[1]) < 2 and int(words[2]) < 2 else 0)]
    if cmd == "tap":
        if MODE == "tapblocked":
            return ["ok tap blocked"]
        node = 0 if MODE == "tapdisagree" else (1 if int(words[1]) < 2 and int(words[2]) < 2 else 0)
        if node == 1 and not model.notice:
            model.press()
        if node == 0 and MODE == "blankchange":
            model.event("blank")
        return ["ok tap %d %d" % (node, node)]
    if cmd == "crop":
        x, w, h = int(words[1]), int(words[3]), int(words[4])
        row = "".join("2196f3ff" if x + i < 2 else "ffffffff" for i in range(w))
        return ["ok crop lines %d" % h] + [row[:-1] if MODE == "cropbad" else row] * h
    if cmd == "ink":
        return ["ok ink lines 2", "ink\t1\t4\t0,0,1,1\t2196f3\t2196f3\tffffff\tffffff", "noink\t0\tunstable"]
    return None


def handle(words, model, state):
    cmd = words[0]
    replies = facts(words, model) if MODE in FACTS and cmd != "open" else special(cmd, model, state)
    if replies is not None:
        return model, replies
    if cmd == "domain-count":
        return model, ["ok domain-count 2"]
    if cmd == "open":
        return Model(int(words[1])), ["ok open"]
    if cmd == "domain-at":
        model.notice = "" if words[1] == "0" else "Pressed"
        return model, ["ok domain-at"]
    if cmd == "apply":
        model.digit = int(words[3])
        return model, [model.apply(int(words[1]), int(words[2]), words[4])]
    if cmd == "hit-test" and MODE == "tapcap":
        return model, ["ok hit-test none"]
    if cmd == "tap" and MODE == "tapcap":
        return model, ["ok tap none none"]
    if cmd == "next-due":
        return model, [next_due(model)]
    if cmd == "advance":
        model.advance(int(words[1]))
        return model, ["ok advance %d" % model.now]
    if cmd == "semantic":
        return model, ["ok semantic lines %d" % len(model.semantic())] + model.semantic()
    if cmd in ("patches", "trace", "frame"):
        items = {"patches": model.patches, "trace": model.trace, "frame": model.frames}[cmd]
        if cmd == "patches":
            model.patches = []
        if cmd == "trace":
            model.trace = []
        return model, ["ok %s lines %d" % (cmd, len(items))] + items
    if cmd == "env-inputs":
        return model, ["ok env-inputs 0" if model.notice else "ok env-inputs 1 1:1:0:-"]
    return model, ["err ? unknown-command"]


def linger():
    """Sleep up to 60 s, but exit as soon as the parent (the explorer) is gone."""
    parent, end = os.getppid(), time.monotonic() + 60
    while os.getppid() == parent and time.monotonic() < end:
        time.sleep(0.1)
    sys.exit(4)


def greeting():
    if MODE == "capflip":
        count = int(open(LOG + ".count").read()) + 1 if os.path.exists(LOG + ".count") else 1
        with open(LOG + ".count", "w") as stream:
            stream.write(str(count))
        return "ui-probe/1 ready tap" if count % 2 else "ui-probe/1 ready"
    if MODE in FACTS:
        return "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop"
    return {"tapcap": "ui-probe/1 ready hit-test tap", "badcap": "ui-probe/1 ready teleport",
            "missed": "ui-probe/1 ready apply-missed", "badorder": "ui-probe/1 ready tap hit-test",
            "dupcap": "ui-probe/1 ready tap tap"}.get(MODE, "ui-probe/1 ready")


def main():
    if LOG:
        with open(LOG + ".pid", "w") as stream:
            stream.write(str(os.getpid()))
    model, state = None, {}
    if MODE == "nogreet":
        linger()
    say(greeting())
    for raw in sys.stdin:
        if LOG:
            with open(LOG, "a") as stream:
                stream.write(raw)
        words = raw.rstrip("\n").split(" ")
        if words[0] == "quit":
            say("ok quit" + ("\ngarbage" if MODE == "quitgarbage" else ""))
            return 1 if MODE == "quitexit1" else 0
        model, replies = handle(words, model, state)
        for line in replies:
            say(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
