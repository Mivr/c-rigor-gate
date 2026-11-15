"""The facts selftest/ui_frame.sh checks in the frame toy's transcripts, reply by reply (python3 -I, stdlib only).

    check.py session <session.in> <session output>
    check.py bad <bad.in> <bad output>
    check.py anim <anim_frame.in> <its output> <anim_plain.in> <its output>
    check.py crop <output of: open, frame, crop 0 0 160 51, crop 0 0 160 52, quit>
"""
import sys

GREETING = "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop"
OVERLAY = 12   # walk index of the overlay (last child of the screen)


def replies(cmd_file, out_file):
    """[(command, header, body lines)]: every reply is one line, or `ok <name> lines <n>` and n lines."""
    cmds = open(cmd_file).read().splitlines()
    lines = open(out_file, encoding="ascii").read().split("\n")
    assert lines.pop() == "" and lines.pop(0) == GREETING
    got, at = [], 0
    for cmd in cmds:
        head = lines[at]
        words = head.split(" ")
        at += 1
        n = int(words[3]) if len(words) == 4 and words[0] == "ok" and words[2] == "lines" else 0
        got.append((cmd, head, lines[at:at + n]))
        at += n
    assert at == len(lines), "lines after the last reply"
    assert all(len(r[1]) + sum(len(l) + 1 for l in r[2]) < 65536 for r in got), "a reply over the payload"
    return got


class Session:
    def __init__(self, cmd_file, out_file):
        self.r = replies(cmd_file, out_file)

    def reply(self, i, cmd):
        assert self.r[i][0] == cmd, (i, self.r[i][0], cmd)
        return self.r[i][1], self.r[i][2]

    def head(self, i, cmd):
        return self.reply(i, cmd)[0]

    def body(self, i, cmd):
        return self.reply(i, cmd)[1]

    def frame(self, i):
        """The lines of a frame reply: the head, then each node of the walk in index order, then the life lines."""
        head, body = self.reply(i, "frame")
        assert head.startswith("ok frame lines "), head
        count = int(body[0].split("\t")[2])
        nodes = [l.split("\t")[1] for l in body if l.startswith("node\t")]
        assert body[0].startswith("lvprobe\t1\t") and body[1].startswith("frame\t") and nodes == [str(k) for k in range(count)]
        kinds = [l.split("\t")[0] for l in body]
        assert kinds == sorted(kinds, key=lambda k: k == "life"), "life lines come last"
        assert set(kinds) <= {"lvprobe", "frame", "node", "label", "fit", "region", "life"}, "a record kind frame never writes"
        return body


def need(body, line, what):
    assert line in body, "%s: %r missing" % (what, line)


def fit(body, node):
    return [l for l in body if l.startswith("fit\t%d\t" % node)][0].split("\t")


def check_session(s):
    first = s.frame(1)
    assert first[0] == "lvprobe\t1\t15" and first[1] == "frame\t160\t120\t3f670cca"
    need(first, "node\t3\t1\t1\tlv_button\t8\t30\t97\t59\t0\t1\t-1\t-1\t0\t0\t2196f3\t255\t255\t1\t0\t0", "button coords")
    need(first, "label\t4\t-\t16\t0\t1\t0\t0\t1\t39\t16\t39\t16\t=Press\t-", "button label")
    need(first, "fit\t4\t1\t0\t35,40,72,49\t30,33,76,52\t0\t0", "button label fit")
    need(first, "label\t10\t-\t16\t0\t1\t0\t0\t1\t10\t16\t10\t16\t=\\xd0\\x99\t-", "the Cyrillic label in its own font")
    need(first, "fit\t10\t1\t0\t131,4,138,17\t126,0,143,19\t0\t0", "its glyph box, nothing missing")
    need(first, "node\t12\t1\t1\tlv_obj\t0\t0\t159\t119\t0\t0\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0", "overlay, not clickable")
    assert s.head(4, "hit-test 53 45") == "ok hit-test 3" and s.head(5, "trace") == "ok trace lines 0"
    assert s.body(6, "crop 140 100 8 2") == ["ff0000ff" * 4 + "0000ffff" * 4] * 2, "crop pixels"
    ink = s.body(7, "ink")
    need(ink, "ink\t7\t0\t-\t000000\t000000\t000000\t000000", "ink 0 of the hidden label")
    need(ink, "ink\t8\t8\t140,100,143,101\tff0000\tff0000\tffffff\tffffff", "ink of the red swatch")
    need(ink, "ink\t10\t112\t131,4,138,17\t212121\t212121\tffffff\tffffff", "ink of the Cyrillic glyph")
    assert s.frame(8) == first, "ink changed the product: the frame after it differs"
    assert s.head(9, "tap 53 45") == "ok tap 3 3"
    assert s.body(10, "trace") == ["1\tbutton_pressed\t1000", "2\tpointer_clicked\t1000", "3\tbutton_clicked\t1000",
                                   "4\tpress\t1000"], "the queued press runs at the tap"
    assert s.head(11, "next-due") == "ok next-due 4000", "the press's notice timeout, without an advance"
    assert s.body(12, "semantic")[2].startswith("notice\tlabel\t\\xd0\\x93\\xd0\\xbe\\xd1\\x82\\xd0\\xbe\\xd0\\xb2\\xd0\\xbe\t8\t66\t60\t16")
    shown = s.frame(13)
    need(shown, "label\t5\t-\t16\t0\t1\t0\t0\t1\t60\t16\t60\t16\t=\\xd0\\x93\\xd0\\xbe\\xd1\\x82\\xd0\\xbe\\xd0\\xb2\\xd0\\xbe\t-",
         "notice in Bulgarian")
    assert fit(shown, 5)[2] == "1" and fit(shown, 5)[6] == "6", "drawn; Montserrat has none of its 6 Cyrillic glyphs"
    assert fit(shown, 6)[-1] == "0" and fit(s.frame(15), 6)[-1] == "1" and fit(s.frame(17), 6)[-1] == "0", "clipped"
    assert [l for l in s.frame(19) if l.startswith("life")] == ["life\t1\tcreated\t0\t-1\t1\t=lv_label"]
    assert [l for l in s.frame(21) if l.startswith("life")] == ["life\t2\tdeleted\t0\t13\t1\t=lv_label"]
    need(s.frame(23), "node\t12\t1\t1\tlv_obj\t0\t0\t159\t119\t0\t1\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0", "overlay, clickable")
    assert s.head(24, "trace") == "ok trace lines 0"
    assert s.head(25, "hit-test 53 45") == "ok hit-test %d" % OVERLAY, "the hit query names the overlay"
    assert s.head(26, "trace") == "ok trace lines 0", "the hit query fired a handler"
    assert s.head(27, "tap 53 45") == "ok tap %d %d" % (OVERLAY, OVERLAY), "the tap goes to the overlay"
    # pointer_clicked: the probe's tap went through the product's own pointer indev
    assert s.body(28, "trace") == ["5\toverlay_pressed\t1000", "6\tpointer_clicked\t1000", "7\toverlay_clicked\t1000"]
    assert s.head(29, "apply 3 1 0 -") == "ok apply missed"
    assert s.body(30, "trace") == ["8\toverlay_pressed\t1000", "9\tpointer_clicked\t1000", "10\toverlay_clicked\t1000"]
    assert s.head(31, "apply 3 3 0 -") == "ok apply"
    s.frame(32)
    assert s.head(33, "hit-test 53 45") == "ok hit-test 3" and s.head(34, "apply 3 1 0 -") == "ok apply"
    assert s.body(35, "trace")[-1] == "14\tpress\t1000"
    assert s.head(36, "apply 3 10 0 -") == "ok apply"
    need(s.frame(37), "label\t2\t-\t16\t0\t1\t0\t0\t1\t40\t16\t40\t16\t=Done\t-", "the work the animation posted, in the frame")
    assert s.body(38, "trace") == ["15\tanim_done\t1000", "16\tanim_done\t1000"], "the posted work ran at the frame's time"
    assert s.frame(40)[1] == "frame\t160\t120\t3f670cca"


BAD_TAIL = [
    ("frame", "err frame too-large"), ("semantic", "err semantic not-open"),            # APP_MANY labels
    ("frame", "err frame model-contract"), ("semantic", "err semantic not-open"),       # a second display
    ("frame", "err frame model-contract"),                                              # no display of LVGL's
    ("frame", "err frame model-contract"),                                              # two pointer indevs
    ("frame", "err frame model-contract"),                                              # a moving tick callback
    ("tap 53 45", "err tap model-contract"), ("semantic", "err semantic not-open"),     # the tick moved in the tap
    ("apply 3 15 0 -", "err apply model-contract"), ("semantic", "err semantic not-open"),  # outside the enum
    ("frame", "err frame model-contract"),                                              # uim_settle refused (frame)
    ("tap 53 45", "err tap model-contract"), ("semantic", "err semantic not-open"),     # uim_settle refused (tap)
    ("frame", "err frame model-contract"),                                              # larger than the ink scratch
    ("frame", "err frame model-contract"), ("semantic", "err semantic not-open"),       # a clock between frames
    ("frame", "err frame model-contract"), ("semantic", "err semantic not-open"),       # work past the retake bound
    ("frame", "fail frame"), ("semantic", "err semantic not-open"),                     # uim_settle fails (frame)
    ("tap 53 45", "fail tap"), ("semantic", "err semantic not-open"),                   # uim_settle fails (tap)
]


def check_bad(cmd_file, out_file):
    got = [(c, h) for c, h, _ in replies(cmd_file, out_file) if h.startswith(("err ", "fail ")) and
           c.split(" ")[0] in ("frame", "semantic", "tap", "apply")]
    assert got[-len(BAD_TAIL):] == BAD_TAIL, got[-len(BAD_TAIL):]


def check_anim(a_in, a_out, b_in, b_out):
    a, b = Session(a_in, a_out), Session(b_in, b_out)
    assert a.head(2, "next-due") == "ok next-due 100" == b.head(2, "next-due")
    need(a.frame(6), "label\t2\t-\t16\t0\t1\t0\t0\t1\t40\t16\t40\t16\t=Done\t-", "the animation's work, in the frame")
    assert a.body(8, "trace") == b.body(6, "trace") == ["0\tboot\t0", "1\tanim_done\t100"], "a frame moved the work"


def check_crop(out_file):
    lines = open(out_file).read().split("\n")
    at = lines.index("ok crop lines 51")
    rows = lines[at + 1:at + 52]
    assert all(len(r) == 1280 and r == r.lower() and set(r) <= set("0123456789abcdef") for r in rows)
    assert rows[0][:8] == "ffffffff" and lines[at + 52] == "err crop bad-arguments" and lines[at + 53] == "ok quit"


def main(argv):
    if argv[1] == "session":
        check_session(Session(argv[2], argv[3]))
    elif argv[1] == "bad":
        check_bad(argv[2], argv[3])
    elif argv[1] == "anim":
        check_anim(*argv[2:6])
    else:
        check_crop(argv[2])
    print("ok")


if __name__ == "__main__":
    main(sys.argv)
