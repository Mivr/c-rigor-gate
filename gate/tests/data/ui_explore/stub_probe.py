"""A fake probe for the ui-explore unit tests: speaks ui-probe/1 for a toy model (a button and a timed notice), and
misbehaves on purpose in the mode named by argv[1]:

    good       deterministic
    nondet     the press event's trace type carries the process id (model-nondeterministic)
    mismatch   the notice label carries the process id after a press (run-twice-mismatch)
    starve     a press arms a timer that re-arms itself 1 ms later on every firing (timer-starvation)
    exit       exits without a reply at the first `apply` (a probe that exits mid-session)
    malformed  replies to `semantic` with a record of the wrong field count
    hang       never replies to `apply`
    errreply   replies `err apply bad-arguments` to `apply`
"""

import os
import sys
import time

MODE = sys.argv[1]
NOTICE_MS = 3000


class Model:
    def __init__(self, origin):
        self.now = origin
        self.notice = ""
        self.due = None
        self.spin = None
        self.seq = 0
        self.trace = []
        self.patches = ["create\tscreen\t-\t-\t-"]
        self.event("boot")

    def event(self, kind):
        self.trace.append("%d\t%s\t%d" % (self.seq, kind, self.now))
        self.seq += 1

    def next_due(self):
        dues = [d for d in (self.due, self.spin) if d is not None]
        return min(dues) if dues else None

    def apply(self, kind, ident):
        if kind == 3 and ident == 1 and not self.notice:
            self.notice = "Pressed" + (str(os.getpid()) if MODE == "mismatch" else "")
            self.due = self.now + NOTICE_MS
            self.spin = self.now + 1 if MODE == "starve" else None
            self.patches.append("set\tnotice\thidden\t1\t0")
            self.event("press-%d" % os.getpid() if MODE == "nondet" else "press")
            return "ok apply"
        if kind == 1 and ident == 1 and not self.notice:
            self.notice, self.due = "Offline", self.now + NOTICE_MS
            self.event("env_offline")
            return "ok apply"
        return "ok apply refused"

    def advance(self, to):
        while self.now < to:
            due = self.next_due()
            self.now = min(to, due) if due is not None else to
            if self.spin is not None and self.now >= self.spin:
                self.spin = self.now + 1
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


def main():
    model = None
    say("ui-probe/1 ready")
    for raw in sys.stdin:
        words = raw.rstrip("\n").split(" ")
        cmd = words[0]
        if cmd == "quit":
            say("ok quit")
            return 0
        if cmd == "domain-count":
            say("ok domain-count 2")
        elif cmd == "open":
            model = Model(int(words[1]))
            say("ok open")
        elif cmd == "domain-at":
            model.notice = "" if words[1] == "0" else "Pressed"
            say("ok domain-at")
        elif cmd == "apply":
            if MODE == "exit":
                return 3
            if MODE == "hang":
                time.sleep(3600)
            if MODE == "errreply":
                say("err apply bad-arguments")
                continue
            say(model.apply(int(words[1]), int(words[2])))
        elif cmd == "next-due":
            due = model.next_due()
            say("ok next-due none" if due is None else "ok next-due %d" % due)
        elif cmd == "advance":
            model.advance(int(words[1]))
            say("ok advance %d" % model.now)
        elif cmd == "frame":
            lines("frame", [])
        elif cmd == "semantic":
            lines("semantic", ["title\tlabel"] if MODE == "malformed" else model.semantic())
        elif cmd == "patches":
            lines("patches", model.patches)
            model.patches = []
        elif cmd == "trace":
            lines("trace", model.trace)
            model.trace = []
        elif cmd == "env-inputs":
            say("ok env-inputs 0" if model.notice else "ok env-inputs 1 1:1:0:-")
        else:
            say("err ? unknown-command")
    return 1


if __name__ == "__main__":
    sys.exit(main())
