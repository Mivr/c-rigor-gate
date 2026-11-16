"""U05d: a declared countdown restart (`[ambient] countdown_restart_role`, docs/ui-explore.md "Countdown restart"). A
tap through the product's pointer entry that restarts a visible countdown changes only that node's text, upwards; with
the declaration that is "changed nothing" (the info `ambient-restart`), anything else is a change as before. Against the
stub probe's U05d modes (gate/tests/data/ui_explore/stub_probe.py: pcount and its broken variants): what the explorer
reports, and (driving the stub directly) the part of the rule that rejects each broken variant. The rule's parts one
at a time and on real LVGL frames: test_ui_explore_restart_rule.py."""

import json

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_probe as up
from rigor_lib import ui_explore_restart as r
from rigor_lib import ui_explore_words as w
from rigor_lib.ui_explore_run import Step
from tests import test_ui_explore_helpers as h
from tests.test_ui_explore_taps import AMBIENT, BLANK, BUTTON, CREATE_LINE, EMPTY, PRESS, PRESS_LINE, SCREEN, TAPS

COUNTDOWN = (', countdown_restart_role = "countdown", '
             'countdown_restart_provenance = "oracle:the stub restarts its countdown on every tap"')
COUNT = "count\tcountdown\t%s\t8\t120\t40\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"
OPEN_KEY = h.toy_key(h.STUB_OPEN_SEMANTIC + [COUNT % "298 s"], "none", [[1, 0, ""]])
PRESSED = ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
           "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
           "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone", COUNT % "298 s"]
PRESSED_KEY = h.toy_key(PRESSED, "pending", [])
RESTART = {"word": BLANK, "node": "count", "old": 298, "new": 300}


def catalogue_text(declaration=COUNTDOWN):
    """The stub catalogue with the taps, `create` and `[ambient]` (touch, plus `declaration`), as text; selftest/ui.sh
    writes it for its two countdown steps."""
    text = h.TOY.read_text()
    for old, new in (TAPS, (PRESS_LINE, CREATE_LINE), (AMBIENT[0], AMBIENT[1] % declaration)):
        if old not in text:
            raise AssertionError("the stub catalogue lacks %r" % old)
        text = text.replace(old, new)
    return text


def tearDownModule():
    h.assert_no_stubs()


class CountdownRestartTest(h.ExploreCase):
    def countdown(self, declaration=COUNTDOWN):
        path = self.tmp / ("countdown%d.toml" % len(list(self.tmp.glob("countdown*.toml"))))
        path.write_text(catalogue_text(declaration))
        return path

    def found(self, mode, paths, code, declaration=COUNTDOWN, summary=None):
        extra = ("--summary", str(summary)) if summary else ()
        _, found = self.replay(mode, paths, *extra, catalogue=self.countdown(declaration), code=code)
        return [(f["check"], f["severity"], f["id"], f["observed"]) for f in found]

    def noop(self, mode, why, declaration=COUNTDOWN, role="countdown"):
        """The complement tap of the open state is noop-tap-effect, and the rule rejects it for `why`."""
        label = "1/298 s" if mode == "ptworun" else "298 s"
        key = h.toy_key(h.STUB_OPEN_SEMANTIC + [COUNT % label], "none", [[1, 0, ""]])
        self.assertEqual(self.found(mode, [[h.OPEN, BLANK]], 1, declaration), [
            ("noop-tap-effect", "error", h.finding_id("noop-tap-effect", ["noop", key, BLANK]),
             {"word": BLANK, "changed": ["patches", "semantic", "frame"]})])
        self.assertEqual(self.verdict(mode, role), (None, why))

    def verdict(self, mode, role="countdown"):
        """The rule's verdict on the stub's complement tap of the open state, from the explorer's own snapshots."""
        session = up.Session([str(h.stub(self.tmp, mode))], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        session.open(1000, 7)
        step = Step(0, BLANK)
        before = w.snapshot(session, step)
        marks = (len(step.acc_patches), len(step.acc_trace))
        session.hit_test(3, 1)
        session.tap(3, 1)
        after = w.snapshot(session, step)
        other, _, _ = w.ambient_split(step.acc_trace[marks[1]:], ("touch",), session.now)
        changed = w.changes(step, marks, before, after, ambient=(other, None))
        return r.verdict(step.acc_patches[marks[0]:], before, after, changed, True, role)

    def test_a_declared_restart_is_refused_and_reported_once_per_state_and_node(self):
        """The complement tap and the root tap both restart the countdown 298 -> 300 from the open state: both are
        refused (no noop-tap-effect), and the one finding of (state, node) is kept, the shortest path's."""
        summary = self.tmp / "s.json"
        self.assertEqual(self.found("pcount", [[h.OPEN, BLANK], [h.OPEN, SCREEN]], 0, summary=summary), [
            ("ambient-restart", "info", h.finding_id("ambient-restart", ["restart", OPEN_KEY, "count"]), RESTART)])
        events = json.loads(summary.read_text())["events"]
        for word in (BLANK, SCREEN):
            self.assertEqual(events[word], {"accepted_states": 0, "refused_states": 1, "missed_states": 0})

    def test_the_restart_the_stub_draws_like_lvgl_is_accepted_by_the_rule(self):
        """The crc, the screen's region and the label's region all change: the rule accepts it."""
        self.assertEqual(self.verdict("pcount"), ([{"node": "count", "old": 298, "new": 300}], None))

    def test_the_finding_is_one_per_state_and_node_whatever_the_walk_order(self):
        """The same restart reached by a longer path (a frame first: the same state) and a shorter one: one finding,
        the shorter path's, in either order."""
        for paths in ([[h.OPEN, "one-frame", BLANK], [h.OPEN, SCREEN]], [[h.OPEN, SCREEN], [h.OPEN, "one-frame", BLANK]]):
            with self.subTest(paths=paths):
                _, found = self.replay("pcount", paths, catalogue=self.countdown(), code=0)
                self.assertEqual([(f["id"], f["path"], f["observed"]) for f in found], [
                    (h.finding_id("ambient-restart", ["restart", OPEN_KEY, "count"]), [h.OPEN, SCREEN],
                     dict(RESTART, word=SCREEN))])

    def test_two_countdowns_restarted_by_one_tap_are_two_findings(self):
        self.assertEqual(sorted(self.found("pdouble", [[h.OPEN, BLANK]], 0)), sorted(
            ("ambient-restart", "info", h.finding_id("ambient-restart", ["restart", self.double_key(), node]),
             {"word": BLANK, "node": node, "old": old, "new": new}) for node, old, new in (("count", 298, 300),
                                                                                         ("count2", 58, 60))))

    @staticmethod
    def double_key():
        second = "count2\tcountdown\t58 m\t8\t140\t40\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"
        return h.toy_key(h.STUB_OPEN_SEMANTIC + [COUNT % "298 s", second], "none", [[1, 0, ""]])

    def test_the_same_restart_without_the_declaration_is_noop_tap_effect(self):
        label = h.toy_key(h.STUB_OPEN_SEMANTIC + [COUNT % "298 s"], "none", [[1, 0, ""]])
        self.assertEqual(self.found("pcount", [[h.OPEN, BLANK]], 1, declaration=""), [
            ("noop-tap-effect", "error", h.finding_id("noop-tap-effect", ["noop", label, BLANK]),
             {"word": BLANK, "changed": ["patches", "semantic", "frame"]})])

    def test_a_countdown_that_skips_forward_is_noop_tap_effect(self):
        self.noop("pskip", "patch text")

    def test_a_restart_with_another_nodes_patch_is_noop_tap_effect(self):
        self.noop("pplus", "patch op")

    def test_a_restart_on_a_node_of_another_role_is_noop_tap_effect(self):
        self.noop("pcount", "role", declaration=COUNTDOWN.replace('"countdown"', '"timer"'), role="timer")

    def test_two_digit_runs_or_changed_text_around_the_digits_are_noop_tap_effect(self):
        for mode in ("ptworun", "ptext"):
            with self.subTest(mode=mode):
                self.noop(mode, "patch text")

    def test_a_new_node_a_flag_change_or_a_life_line_is_noop_tap_effect(self):
        for mode, why in (("pnode", "semantic shape"), ("pflag", "semantic"), ("plife", "frame life")):
            with self.subTest(mode=mode):
                self.noop(mode, why)

    def test_a_frame_change_beyond_the_countdowns_repaint_is_noop_tap_effect(self):
        """A region of a node whose box does not meet the label's (the button's), the label's own node record (its bg)
        or label record (its font), and a decoy label showing the same texts."""
        for mode, why in (("pframe", "frame record region 1"), ("pbg", "frame record node 2"),
                          ("pfont", "frame record label 2"), ("pdecoy", "frame label match")):
            with self.subTest(mode=mode):
                self.noop(mode, why)

    def test_the_same_restart_on_a_refused_apply_is_the_contract_error_as_before(self):
        """Not a tap: the rule does not apply, so a refused input that restarts the countdown changed the model."""
        found = self.found("pcount", [[h.OPEN, EMPTY]], 1)
        self.assertEqual([(c, o["kind"], o["detail"]) for c, _, _, o in found], [
            ("probe-internal-error", "contract", "a refused input changed the model: patches, semantic, frame")])

    def test_a_probe_tap_on_a_node_without_an_intent_is_missed_when_it_only_restarts(self):
        """Under the notice the button has no intent: a tap that only restarts the countdown is intent-missed (and the
        info); without the declaration the restart made it `ok`."""
        found = self.found("pcount", [[h.OPEN, PRESS, BUTTON]], 1)
        self.assertEqual([(c, i, o) for c, _, i, o in found], [
            ("ambient-restart", h.finding_id("ambient-restart", ["restart", PRESSED_KEY, "count"]),
             dict(RESTART, word=BUTTON)),
            ("intent-missed", h.finding_id("intent-missed", ["missed", PRESSED_KEY, BUTTON]),
             {"word": BUTTON, "applies": ["missed"]})])
        self.assertEqual(self.found("pcount", [[h.OPEN, PRESS, BUTTON]], 0, declaration=""), [])

    def test_the_declaration_is_strict(self):
        base = self.countdown("")
        good = 'ambient = { trace = ["touch"], trace_provenance = "oracle:x"%s }'
        for text, why in (
                (', countdown_restart_role = "countdown"', "countdown_restart_role and countdown_restart_provenance go"),
                (', countdown_restart_provenance = "oracle:y"', "go together"),
                (', countdown_restart_role = "", countdown_restart_provenance = "oracle:y"',
                 "ambient.countdown_restart_role"),
                (', countdown_restart_role = "a\\tb", countdown_restart_provenance = "oracle:y"',
                 "ambient.countdown_restart_role"),
                (', countdown_restart_role = 3, countdown_restart_provenance = "oracle:y"',
                 "ambient.countdown_restart_role"),
                (', countdown_restart_role = "countdown", countdown_restart_provenance = "y"', "provenance")):
            with self.subTest(text=text):
                with self.assertRaises(Exception) as caught:
                    catalogue_mod.loads(self._with(base, good % text))
                self.assertIn(why, str(caught.exception))
        self.assertEqual(catalogue_mod.loads(self._with(base, good % COUNTDOWN)).countdown_role, "countdown")
        self.assertIsNone(catalogue_mod.loads(self._with(base, good % "")).countdown_role)

    @staticmethod
    def _with(base, ambient):
        text = base.read_text()
        start = text.index("ambient = {")
        return (text[:start] + ambient + text[text.index("\n", start):]).encode()


