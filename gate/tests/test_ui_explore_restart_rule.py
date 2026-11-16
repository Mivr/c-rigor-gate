"""U05d: the countdown restart rule (gate/rigor_lib/ui_explore_restart.py) one part at a time on snapshots, each
rejection with its reason, and its frame clause on a real LVGL frame: the frame toy's checked-in transcript
(selftest/ui_frame_product/session.out, which selftest/ui_frame.sh checks byte for byte against the real probe), where
an input repaints one label (`Frame` -> `Done`) and with it the regions of every node whose box covers it."""

import unittest

from rigor_lib import ui_explore_grammar as g
from rigor_lib import ui_explore_restart as r
from tests import test_ui_explore_helpers as h

COUNT = "count\tcountdown\t%s\t8\t120\t40\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"
TITLE = "title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"
SCREEN = "node\t0\t-1\t0\tlv_obj\t0\t0\t99\t99\t0\t1\t-1\t-1\t0\t0\tffffff\t255\t255\t1\t0\t0"
LABEL_NODE = "node\t2\t0\t1\tlv_label\t%s\t0\t0\t-1\t-1\t0\t0\t%s\t0\t0\t1\t0\t0"
FAR = "node\t8\t0\t1\tlv_obj\t90\t90\t99\t99\t0\t0\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0"
TRANSCRIPT = h.REPO / "selftest" / "ui_frame_product" / "session.out"
SCENE = ("patches", "semantic", "frame")


def frame(text, crc="1", box="10,10,40,20", screen="a", bg="ffffff", font="-", far="f", node8=FAR):
    """A frame of a screen, the countdown's lv_label (node 2) inside it and a node far from it (node 8)."""
    return ["lvprobe\t1\t3", "frame\t100\t100\t" + crc, SCREEN, "region\t0\t" + screen,
            LABEL_NODE % (box.replace(",", "\t"), bg),
            "label\t2\t%s\t16\t0\t1\t0\t0\t1\t40\t16\t40\t16\t=%s\t-" % (font, text),
            "fit\t2\t1\t0\t1,1,2,2\t1,1,2,2\t0\t0", "region\t2\t" + text.replace(" ", "_"), node8, "region\t8\t" + far]


def snapshot(label, life=(), extra=(), **frame_args):
    return {"semantic": [TITLE, COUNT % label] + list(extra), "frame": frame(label, **frame_args), "life": list(life),
            "due": None, "env": []}


def patch(old="298 s", new="300 s", op="update", field="text", key="count"):
    return g.parse_record("patches", "\t".join((op, key, field, old, new)))


def real_frames(text):
    """The `frame` replies of a probe transcript, each as its lines without `taps` and `life`."""
    lines, out = text.split("\n"), []
    for i, line in enumerate(lines):
        if line.startswith("ok frame lines "):
            body = lines[i + 1:i + 1 + int(line.rsplit(" ", 1)[1])]
            out.append([x for x in body if not x.startswith(("taps\t", "life\t"))])
    return out


def real_repaint(text, old, new):
    """The first pair of consecutive frames of a transcript in which a `label` record goes from `old` to `new`."""
    frames = real_frames(text)
    for before, after in zip(frames, frames[1:]):
        if "=" + old in [x.split("\t")[13] for x in before if x.startswith("label\t")] and \
                "=" + new in [x.split("\t")[13] for x in after if x.startswith("label\t")]:
            return before, after
    raise AssertionError("no repaint %r -> %r in the transcript" % (old, new))


class RuleTest(unittest.TestCase):
    BEFORE = snapshot("298 s")

    def verdict(self, patches, after, changed=SCENE, frame_compared=True):
        return r.verdict(patches, self.BEFORE, after, list(changed), frame_compared, "countdown")

    def test_forward(self):
        self.assertEqual(r.forward(b"298 s", b"300 s"), (298, 300))
        self.assertEqual(r.forward(b"300 s", b"300 s"), (300, 300))
        self.assertEqual(r.forward(b"9" * 18, b"9" * 18), (10 ** 18 - 1, 10 ** 18 - 1))
        for old, new in ((b"300 s", b"298 s"), (b"1/298 s", b"1/300 s"), (b"298 s", b"300 sec"), (b"s", b"s"),
                         (b"298 s", b"x300 s"), (b"1" * 19, b"2" * 19), (b"1" * 4400, b"2" * 4400)):
            with self.subTest(old=old[:20], new=new[:20]):
                self.assertIsNone(r.forward(old, new))

    def test_the_restart_and_its_repaint_are_accepted(self):
        restart = ([{"node": "count", "old": 298, "new": 300}], None)
        self.assertEqual(self.verdict([patch()], snapshot("300 s", crc="2", screen="b", box="10,10,42,20")), restart)
        self.assertEqual(self.verdict([patch("298 s", "299 s"), patch("299 s", "300 s")], snapshot("300 s")), restart)
        self.assertEqual(self.verdict([patch()], snapshot("300 s", font="9"), frame_compared=False), restart)

    def test_each_part_of_the_scene_and_the_patches(self):
        title = patch("Toy 1", "Toy 2", key="title")
        for name, patches, after, changed, why in (
                ("no patch", [], snapshot("300 s"), ("semantic",), "no patch"),
                ("a set patch", [patch(op="set")], snapshot("300 s"), SCENE, "patch op"),
                ("another field", [patch(field="hidden")], snapshot("300 s"), SCENE, "patch op"),
                ("a node of another role", [title], snapshot("300 s"), SCENE, "role"),
                ("a key not in the tree", [patch(key="gone")], snapshot("300 s"), SCENE, "role"),
                ("a backward patch", [patch("300 s", "298 s")], snapshot("300 s"), SCENE, "patch text"),
                ("a backward label", [patch()], snapshot("290 s"), SCENE, "patch chain"),
                ("a patch with the tree unchanged", [patch()], snapshot("298 s"), ("patches",),
                 "patch without a label change"),
                ("a patch from another old text", [patch("297 s", "300 s")], snapshot("300 s"), SCENE, "patch chain"),
                ("a broken chain", [patch("298 s", "299 s"), patch("298 s", "300 s")], snapshot("300 s"), SCENE,
                 "patch chain"),
                ("a patch to another new text", [patch("298 s", "301 s")], snapshot("300 s"), SCENE, "patch chain"),
                ("a node added", [patch()], snapshot("300 s", extra=[TITLE]), SCENE, "semantic shape"),
                ("a trace record", [patch()], snapshot("300 s"), ("patches", "trace", "semantic"), "part trace"),
                ("a deadline", [patch()], snapshot("300 s"), ("patches", "due"), "part due"),
                ("env", [patch()], snapshot("300 s"), ("patches", "env"), "part env")):
            with self.subTest(name=name):
                self.assertEqual(self.verdict(patches, after, changed), (None, why))

    def test_each_part_of_the_frame(self):
        moved = FAR.replace("\t90\t90\t", "\t0\t0\t")
        relabelled = FAR.replace("lv_obj", "lv_label")
        for name, after, why in (
                ("a life line", snapshot("300 s", life=["life\t1\tcreated\t0\t-1\t0\t=x"]), "frame life"),
                ("a label not showing the node's text", dict(snapshot("300 s"), frame=frame("301 s")),
                 "frame label match"),
                ("the label's bg", snapshot("300 s", bg="ff0000"), "frame record node 2"),
                ("the label's font", snapshot("300 s", font="3"), "frame record label 2"),
                ("a far node's region", snapshot("300 s", far="g"), "frame record region 8"),
                ("a node moved over the label", snapshot("300 s", node8=moved, far="g"), "frame record node 8"),
                ("another node's own record", snapshot("300 s", node8=relabelled), "frame record node 8")):
            with self.subTest(name=name):
                self.assertEqual(self.verdict([patch()], after), (None, why))
        for index, line, why in ((1, "frame\t101\t100\t2", "frame record frame"),
                                 (0, "lvprobe\t1\t4", "frame record lvprobe")):
            after = snapshot("300 s")
            after["frame"][index] = line
            self.assertEqual(self.verdict([patch()], after), (None, why))

    def test_a_decoy_label_with_the_same_texts_rejects(self):
        def two(text):
            return frame(text) + [LABEL_NODE.replace("\t2\t", "\t5\t", 1) % ("50\t50\t60\t60", "ffffff"),
                                  "label\t5\t-\t16\t0\t1\t0\t0\t1\t40\t16\t40\t16\t=%s\t-" % text]
        before = dict(self.BEFORE, frame=two("298 s"))
        after = dict(snapshot("300 s"), frame=two("300 s"))
        self.assertEqual(r.verdict([patch()], before, after, list(SCENE), True, "countdown"),
                         (None, "frame label match"))

    def test_the_frame_clause_on_a_real_lvgl_repaint(self):
        """A real repaint of the toy's title: its node's box, label metrics, fit and region change, and so do the
        regions of the screen, the layers and the full-screen overlay that cover it, and the crc. Accepted; a change of
        a node that does not cover the label, or of a covering node's own record, is not."""
        before, after = real_repaint(TRANSCRIPT.read_text(), "Frame", "Done")
        self.assertGreater(sum(1 for a, b in zip(before, after) if a != b and a.startswith("region\t")), 3)
        labels = {"title": ("Frame", "Done")}
        self.assertIsNone(r.frame_reason(before, after, [], labels))
        for prefix, old, new, why in (("region\t8\t", None, "region\t8\t00000000", "frame record region 8"),
                                      ("node\t12\t", "\tffffff\t", "\tff0000\t", "frame record node 12")):
            index = [i for i, line in enumerate(after) if line.startswith(prefix)][0]
            bad = list(after)
            bad[index] = new if old is None else after[index].replace(old, new)
            self.assertEqual(r.frame_reason(before, bad, [], labels), why)
        self.assertEqual(r.frame_reason(before, after, [], {"title": ("Frame", "Dome")}), "frame label match")
