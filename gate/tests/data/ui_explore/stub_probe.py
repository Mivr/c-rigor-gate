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
    tapcap       announces the tap capability and answers `tap x y`
    badcap       announces an unknown capability
    framelines   replies to `frame` with two escaped seam lines
    nodomain     domain-count 0
"""

import os
import subprocess
import sys
import time

MODE = sys.argv[1]
NOTICE_MS = 3000
LOG = os.environ.get("UI_STUB_LOG")


class Model:
    def __init__(self, origin):
        self.now = origin
        self.notice = ""
        self.due = None
        self.spin = None
        self.tick = origin + 250 if MODE == "tick" else None
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
        self.due = {"far": self.now + (1 << 40), "beyond": (1 << 53)}.get(MODE, self.due)
        self.spin = self.now + 1 if MODE == "starve" else None
        self.zero = MODE in ("duenow", "duenowerr")
        self.patches.append("set\tnotice\thidden\t1\t0")
        self.event("press-%d" % os.getpid() if MODE == "nondet" else "press")

    def apply(self, kind, ident, text):
        if MODE == "refuseall":
            return "ok apply refused"
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
        return "ok apply refused"

    def advance(self, to):
        while self.now < to:
            due = self.next_due()
            self.now = min(to, due) if due is not None else to
            if self.spin is not None and self.now >= self.spin:
                self.spin = self.now + 1
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
        time.sleep(3600)
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
    if cmd == "semantic" and MODE == "malformed":
        return ["ok semantic lines 1", "title\tlabel"]
    if cmd == "frame" and MODE == "framelines":
        return ["ok frame lines 2", "obj\tlabel\tA\\tB", "crc\t\\x01ff"]
    if cmd == "apply" and MODE == "extra" and not state.get("extra"):
        state["extra"] = True
        return [model.apply(3, 1, "-"), "stray output"]
    return None


def handle(words, model, state):
    cmd = words[0]
    replies = special(cmd, model, state)
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
        return model, [model.apply(int(words[1]), int(words[2]), words[4])]
    if cmd == "tap" and MODE == "tapcap":
        return model, ["ok tap refused"]
    if cmd == "next-due":
        return model, [next_due(model)]
    if cmd == "advance":
        model.advance(int(words[1]))
        return model, ["ok advance %d" % model.now]
    if cmd == "semantic":
        return model, ["ok semantic lines %d" % len(model.semantic())] + model.semantic()
    if cmd in ("patches", "trace", "frame"):
        items = {"patches": model.patches, "trace": model.trace, "frame": []}[cmd]
        if cmd == "patches":
            model.patches = []
        if cmd == "trace":
            model.trace = []
        return model, ["ok %s lines %d" % (cmd, len(items))] + items
    if cmd == "env-inputs":
        return model, ["ok env-inputs 0" if model.notice else "ok env-inputs 1 1:1:0:-"]
    return model, ["err ? unknown-command"]


def main():
    if LOG:
        with open(LOG + ".pid", "w") as stream:
            stream.write(str(os.getpid()))
    model, state = None, {}
    say({"tapcap": "ui-probe/1 ready tap", "badcap": "ui-probe/1 ready teleport"}.get(MODE, "ui-probe/1 ready"))
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
