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

Intent 7 creates an object (a `life` line in the next frame only) in these modes. The frame-facts modes announce every capability (`frame-facts ink hit-test tap apply-missed crop`, as the C probe does)
and model a 4x2 display: walk node 0 the screen, node 1 a 2x2 button at (0, 0) whose tap presses like intent 1; while
the notice is shown the button's tap changes nothing (the F3b canary) and intent 1 is `ok apply missed`:
    facts        correct frame records, hit-test, tap, crop and ink
    framebad     the button's `node` record has 20 fields
    frametype    the frame has a record of an unknown type
    framenum     the button's `node` record has a non-numeric index
    refuselife   a refused wedge line creates an object (a `life` line in the next frame)
    framework    the button's tap only queues the press; it runs when `frame` runs the product's due work
    misroute     a transparent overlay (node 2, not a root) covers the button and takes every tap
    tapnone      `tap` replies `ok tap none 1`
    wide         the display is 9000 pixels wide and the button 9000 wide (crops are banded and the image capped)
    tapblocked   `hit-test` and `tap` reply blocked
    tapdisagree  `tap` presses the screen where `hit-test` found the button
    noframe      `hit-test` replies `err hit-test no-frame`
    toolarge     `frame` replies `err frame too-large`
    blankchange  a tap on the screen (outside the button) emits a trace event
    cropbad      `crop` rows are one hex digit short

U05c, the product's pointer entry: these frame-facts modes announce `pointer` too (all but `pindev`) and write the
`taps` line in the first frame of a session (`entry`; `indev` for `pindev`). Every tap is a sample through the entry:
    ptouch       every tap posts one `touch` at its instant (a correct product with an ambient event)
    pnotouch     a tap posts no `touch` (ambient-missing)
    ptwice       a tap posts `touch` twice (ambient-extra)
    pchange      as ptouch, and a tap on the screen (outside the button) also emits a patch (noop-tap-effect)
    prestart     as ptouch, and every tap restarts an idle deadline 5000 ms later (armed at open; it does nothing)
    pindev       no `pointer`: taps are injected at the product's own indev (`taps indev`: taps-injected)

U05d, a countdown restarted by every sample (as ptouch, plus a semantic node `count` of role `countdown` showing
"298 s", drawn as the frame's node 2, an lv_label at 2,1..3,1 whose text is the label; as on a real LVGL frame, the
crc, the screen's region (its box covers the label) and the label's own region follow the text, the button's (0,0..1,1,
not meeting the label) does not). The first tap, and the first refused apply, restart it to 300 (patch
`update count text 298 s 300 s`); a later one changes nothing, as the value is already 300:

    pcount       exactly that (a declared countdown restart)
    pskip        the restart sets 290: the countdown skips forward
    pplus        the restart also patches another node (`set notice hidden 1 0`)
    ptworun      the label is "1/298 s" -> "1/300 s" (two runs of digits)
    ptext        the label is "298 s" -> "300 sec" (the text around the digits changes)
    pnode        the restart also adds a semantic node (a navigation)
    pflag        the restart also changes the countdown node's flags
    pframe       the restart also changes the button's frame region
    plife        the restart also creates an object (a `life` line)
    pbg          the restart also changes the countdown node's bg colour (its own `node` record)
    pfont        the restart also changes the countdown label's font id (its own `label` record)
    pdecoy       a second lv_label (node 3) shows the same text as the countdown, before and after
    pdouble      a second countdown `count2` (node 3, "58 m" -> "60 m") restarts with the first

U24, scene identity: as facts, announcing `identity` too; the modes and their replies are in stub_identity.py.

In every mode intent 2 is accepted only while the notice is shown (trace `late`), intent 10 is a pad digit (accepted,
trace `digit`) and intent 11 the pad's enter (accepted after a digit, trace `enter`). A stub that would sleep exits as
soon as its parent is gone, so a killed explorer never leaves one behind.
"""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I leaves the script's directory off the path
import stub_identity  # noqa: E402

MODE = sys.argv[1]
NOTICE_MS = 3000
FACTS = ("facts", "framebad", "frametype", "tapblocked", "tapdisagree", "noframe", "toolarge", "blankchange", "cropbad",
         "refuselife", "framework", "misroute", "tapnone", "framenum", "wide", "ptouch", "pnotouch", "ptwice", "pchange",
         "prestart", "pindev")
COUNT = ("pcount", "pskip", "pplus", "ptworun", "ptext", "pnode", "pflag", "pframe", "plife", "pbg", "pfont", "pdecoy",
         "pdouble")
IDENT = stub_identity.MODES
FACTS += COUNT + IDENT
POINTER = ("ptouch", "pnotouch", "ptwice", "pchange", "prestart") + COUNT
IDLE_MS = 5000
SCREEN = "node\t0\t-1\t0\tlv_obj\t0\t0\t3\t1\t0\t1\t-1\t-1\t0\t0\tffffff\t255\t255\t1\t0\t0"
BUTTON = "node\t1\t0\t1\tlv_button\t0\t0\t1\t1\t0\t1\t-1\t-1\t0\t0\t2196f3\t255\t255\t1\t0\t0"
OVERLAY = "node\t2\t0\t1\tlv_obj\t0\t0\t3\t1\t0\t1\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0"
COUNT_NODE = "node\t%d\t0\t1\tlv_label\t%s\t0\t0\t-1\t-1\t0\t0\t%s\t0\t0\t1\t0\t0"
COUNT_LABEL = "label\t%d\t%s\t16\t0\t0\t0\t0\t1\t40\t16\t40\t16\t=%s\t-"
FACT_FRAME = ["lvprobe\t1\t2", "frame\t4\t2\t0badcafe", SCREEN, "region\t0\t0badcafe", BUTTON, "region\t1\t12345678"]
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
        self.life = ["life\t0\tcreated\t0\t-1\t0\t=lv_\\x01obj"]   # in the first frame after its event only
        self.queued = False
        self.framed = False         # the session's first frame carries the `taps` line (U05c modes)
        self.idle = origin + IDLE_MS if MODE == "prestart" else None
        self.count, self.restarted = (298 if MODE in COUNT else None), False
        self.count2 = 58 if MODE == "pdouble" else None
        self.event("boot")

    def count_label(self):
        text = "%d s" % self.count
        return "1/" + text if MODE == "ptworun" else text + "ec" if MODE == "ptext" and self.restarted else text

    def restart(self):
        """The countdown restart of the U05d modes: 298 -> 300 (pskip: 290), once."""
        if self.restarted:
            return
        old = self.count_label()
        self.count, self.restarted = (290 if MODE == "pskip" else 300), True
        self.patches.append("update\tcount\ttext\t%s\t%s" % (old, self.count_label()))
        if MODE == "pdouble":
            self.count2 = 60
            self.patches.append("update\tcount2\ttext\t58 m\t60 m")
        if MODE == "pplus":
            self.patches.append("set\tnotice\thidden\t1\t0")
        if MODE == "plife":
            self.life.append("life\t9\tcreated\t0\t-1\t0\t=lv_label")

    def event(self, kind):
        self.trace.append("%d\t%s\t%d" % (self.seq, kind, self.now))
        self.seq += 1

    def next_due(self):
        dues = [d for d in (self.due, self.spin, self.tick, self.idle) if d is not None]
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
        if MODE in FACTS and kind == 3 and ident == 7:
            self.life.append("life\t%d\tcreated\t0\t-1\t0\t=lv_label" % len(self.trace))
            self.event("create")
            return "ok apply"
        if MODE == "refuselife" and kind == 2 and text == "-":
            self.life.append("life\t9\tcreated\t0\t-1\t0\t=lv_label")
            return "ok apply refused"
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
        if MODE in COUNT:
            self.restart()
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
            if self.idle is not None and self.now >= self.idle:
                self.idle = None
            if self.due is not None and self.now >= self.due:
                self.notice, self.due = "", None
                self.patches.append("set\tnotice\thidden\t0\t1")
                self.event("notice_timeout")

    def semantic(self):
        flags = "-" if self.notice else "hidden"
        return ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
                "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
                "notice\tlabel\t%s\t8\t90\t%d\t16\t1\t-\t%s\tbody\tnormal\tnone\tnone" % (self.notice, 8 * len(self.notice), flags)] \
            + self.count_semantic()

    def count_semantic(self):
        if self.count is None:
            return []
        flags = "urgent" if MODE == "pflag" and self.restarted else "-"
        extra = ["more\tlabel\tMore\t8\t140\t32\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"] \
            if MODE == "pnode" and self.restarted else []
        if MODE == "pdouble":
            extra.append("count2\tcountdown\t%d m\t8\t140\t40\t16\t1\t-\t-\tbody\tnormal\tnone\tnone" % self.count2)
        return ["count\tcountdown\t%s\t8\t120\t40\t16\t1\t-\t%s\tbody\tnormal\tnone\tnone" % (self.count_label(), flags)] + extra


def count_frame(model, frame):
    """The U05d modes' frame (in place): the countdown's lv_label (node 2) and, in pdecoy and pdouble, node 3; the crc,
    the screen's region and each label's region follow the texts, as on a real LVGL frame."""
    nodes = [(2, model.count_label(), "2\t1\t3\t1")]
    if MODE in ("pdecoy", "pdouble"):
        nodes.append((3, model.count_label() if MODE == "pdecoy" else "%d m" % model.count2, "0\t1\t1\t1"))
    pixels = "%08x" % sum("".join(text for _, text, _ in nodes).encode())
    frame[0], frame[1], frame[3] = "lvprobe\t1\t%d" % (2 + len(nodes)), "frame\t4\t2\t" + pixels, "region\t0\t" + pixels
    changed = model.restarted
    for index, text, box in nodes:
        bg = "ff0000" if MODE == "pbg" and changed and index == 2 else "ffffff"
        font = "1" if MODE == "pfont" and changed and index == 2 else "-"
        frame += [COUNT_NODE % (index, box, bg), COUNT_LABEL % (index, font, text),
                  "region\t%d\t%08x" % (index, sum(text.encode()) + index)]
    if MODE == "pframe" and changed:
        frame[5] = "region\t1\t87654321"


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


def fact_frame(model):
    """The frame records, then the `life` lines queued since the last frame (each in one frame only)."""
    frame = list(FACT_FRAME)
    if MODE == "framebad":
        frame[4] = BUTTON.rsplit("\t", 1)[0]
    if MODE == "frametype":
        frame.append("bogus\t1")
    if MODE == "framenum":
        frame[4] = BUTTON.replace("node\t1\t", "node\tx\t")
    if MODE == "misroute":
        frame[0] = "lvprobe\t1\t3"
        frame.insert(6, OVERLAY)
    if MODE == "wide":
        frame[1] = "frame\t9000\t2\t0badcafe"
        frame[4] = BUTTON.replace("\t1\t1\t0\t1\t-1", "\t8999\t1\t0\t1\t-1")
    if model.count is not None:
        count_frame(model, frame)
    if (MODE in POINTER or MODE == "pindev") and not model.framed:
        frame.insert(2, "taps\t%s" % ("indev" if MODE == "pindev" else "entry"))
    model.framed = True
    frame += model.life
    model.life = []
    return frame


def hit(words):
    """The node at a point: the overlay (misroute mode) covers everything, else the button holds x < 2, y < 2."""
    if MODE == "misroute":
        return 2
    return 1 if int(words[1]) < 2 and int(words[2]) < 2 else 0


def facts(words, model):
    """Replies of the frame-facts modes to frame, hit-test, tap, crop and ink; None for every other command."""
    cmd = words[0]
    if cmd == "frame":
        if MODE == "toolarge":
            return ["err frame too-large"]
        if model.queued:            # framework: the press queued by the tap runs when the frame runs due work
            model.queued = False
            model.press()
        frame = fact_frame(model)
        return ["ok frame lines %d" % len(frame)] + frame
    if cmd == "hit-test":
        if MODE in ("tapblocked", "noframe"):
            return ["ok hit-test blocked" if MODE == "tapblocked" else "err hit-test no-frame"]
        return ["ok hit-test %d" % hit(words)]
    if cmd == "tap":
        if MODE == "tapblocked":
            return ["ok tap blocked"]
        if MODE == "tapnone":
            return ["ok tap none 1"]
        node = 0 if MODE == "tapdisagree" else hit(words)
        for _ in range({"ptouch": 1, "pchange": 1, "prestart": 1, "ptwice": 2}.get(MODE, 1 if MODE in COUNT else 0)):
            model.event("touch")     # the entry's own event, at the tap's instant
        if MODE in COUNT:
            model.restart()
        if MODE == "prestart":
            model.idle = model.now + IDLE_MS
        if node == 0 and MODE == "pchange":
            model.patches.append("set\tscreen\tcolor\twhite\tgrey")
        if node == 1 and not model.notice and MODE == "framework":
            model.queued = True
        elif node == 1 and not model.notice:
            model.press()
        if node == 0 and MODE == "blankchange":
            model.event("blank")
        return ["ok tap %d %d" % (node, node)]
    if cmd == "crop":
        x, w, h = int(words[1]), int(words[3]), int(words[4])
        row = "".join("2196f3ff" if x + i < 2 else "ffffffff" for i in range(w))
        return ["ok crop lines %d" % h] + [row[:-1] if MODE == "cropbad" else row] * h
    if cmd == "identity":
        return stub_identity.reply(MODE, model)
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
        tail = " pointer" if MODE in POINTER else " identity" if MODE in IDENT else ""
        return "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop" + tail
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
