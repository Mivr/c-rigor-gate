"""The facts of the taps session (pointer.in, U05c) on the toy's two builds, reply by reply. Stdlib only.

    python3 -I pointer_check.py entry|noentry SESSION TRANSCRIPT

`entry`: the build with the pointer entry (probe_pointer): the greeting announces `pointer`; a tap at the button posts
`touch` and the click's `press` at the tap's instant, pressing and clicking node 3 (the lv_button); under the notice the
scrim (node 6) takes the tap and only `touch` is posted; with the app's indev disabled the tap is blocked (the hit query
agrees) and the entry still posts `touch`, which LVGL then drops; after the notice times out the next tap presses the
button again, at the new time. `noentry`: the build without it (probe): no `pointer` capability, the same pressed and
clicked nodes and blocked tap, and no `touch` anywhere. Exit 0 when every fact holds, 1 otherwise (each failed fact
printed).
"""

import re
import sys

GREETING = "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop"


def replies(session, out):
    """[(command, header, body lines)] paired by position; a header `ok <x> lines <n>` owns the n lines after it."""
    commands = [c for c in session.split("\n") if c]
    lines = out.split("\n")
    if lines[-1] == "":
        lines.pop()
    pairs, k = [], 1
    for command in commands:
        if k >= len(lines):
            raise ValueError("no reply to %r" % command)
        head, body = lines[k], []
        k += 1
        m = re.fullmatch(r"ok \S+ lines (\d+)", head)
        if m:
            body = lines[k:k + int(m.group(1))]
            k += int(m.group(1))
        pairs.append((command, head, body))
    if k != len(lines):
        raise ValueError("%d lines after the last reply" % (len(lines) - k))
    return lines[0], pairs


def node(frame, index):
    """(class, box) of node `index` of a frame reply."""
    for line in frame:
        f = line.split("\t")
        if f[0] == "node" and f[1] == str(index):
            return f[4], ",".join(f[5:9])
    return None


def trace(body):
    return [tuple(line.split("\t")[1:]) for line in body]


def check(mode, greeting, ex):
    entry = mode == "entry"
    touch = (lambda ms: [("touch", ms)]) if entry else (lambda ms: [])
    want = [
        ("frame", None, None),
        ("trace", None, [("boot", "1000")]),
        ("hit-test 57 57", "ok hit-test 3", None),
        ("tap 57 57", "ok tap 3 3", None),
        ("trace", None, touch("1000") + [("press", "1000")]),     # the touch and the click's work at the tap's instant
        ("semantic", None, None),
        ("next-due", "ok next-due 4000", None),
        ("frame", None, None),
        ("hit-test 57 57", "ok hit-test 6", None),
        ("tap 57 57", "ok tap 6 6", None),                         # the notice's scrim takes it (F3b)
        ("trace", None, touch("1000")),
        ("apply 3 673 0 -", "ok apply", None),                     # the app's indev disabled
        ("frame", None, None),
        ("hit-test 57 57", "ok hit-test blocked", None),
        ("tap 57 57", "ok tap blocked", None),
        ("trace", None, touch("1000")),                            # delivered by the entry, dropped by LVGL
        ("apply 3 673 0 -", "ok apply", None),
        ("advance 4000", "ok advance 4000", None),
        ("trace", None, [("notice_timeout", "4000")]),
        ("frame", None, None),
        ("tap 57 57", "ok tap 3 3", None),
        ("trace", None, touch("4000") + [("press", "4000")]),
        ("quit", "ok quit", None),
    ]
    bad = []
    if greeting != GREETING + (" pointer" if entry else ""):
        bad.append("greeting %r" % greeting)
    commands = [("open 1000 1", "ok open", None)] + want
    if [c for c, _, _ in ex] != [c for c, _, _ in commands]:
        return bad + ["the session is not pointer.in: %r" % [c for c, _, _ in ex]]
    for i, ((command, head, body), (_, want_head, want_trace)) in enumerate(zip(ex, commands)):
        if want_head is not None and head != want_head:
            bad.append("reply %d (%s): %r, want %r" % (i + 1, command, head, want_head))
        if want_trace is not None and trace(body) != want_trace:
            bad.append("reply %d (%s): %r, want %r" % (i + 1, command, trace(body), want_trace))
    first, notice = ex[1][2], ex[8][2]
    if node(first, 3) != ("lv_button", "8,40,107,75") or node(notice, 6) != ("lv_obj", "0,0,159,119"):
        bad.append("node 3 is not the button or node 6 not the scrim: %r %r" % (node(first, 3), node(notice, 6)))
    if any(("touch" in line) for _, _, b in ex for line in b) != entry:
        bad.append("a touch %s" % ("is missing" if entry else "without the pointer entry"))
    return bad


def main(argv):
    if len(argv) != 4 or argv[1] not in ("entry", "noentry"):
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    try:
        with open(argv[2], encoding="ascii") as f:
            session = f.read()
        with open(argv[3], encoding="ascii") as f:
            out = f.read()
        greeting, ex = replies(session, out)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print("pointer_check: %s" % exc, file=sys.stderr)
        return 1
    bad = check(argv[1], greeting, ex)
    for b in bad:
        print("pointer_check: FAIL: %s" % b)
    if not bad:
        print("pointer_check: %s: %d replies as expected" % (argv[1], len(ex)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
