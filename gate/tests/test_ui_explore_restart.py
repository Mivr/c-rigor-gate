"""U05d: a declared countdown restart (`[ambient] countdown_restart_role`, docs/ui-explore.md "Countdown restart"). A
tap through the product's pointer entry that restarts a visible countdown changes only that node's text, upwards; with
the declaration that is "changed nothing" (the info `ambient-restart`), anything else is a change as before. Against the
stub probe's U05d modes (gate/tests/data/ui_explore/stub_probe.py: pcount and its broken variants)."""

import json

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_grammar as g
from rigor_lib import ui_explore_restart as r
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
RESTART = {"word": BLANK, "restarts": [{"node": "count", "old": 298, "new": 300}]}


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

    def noop(self, mode, changed, declaration=COUNTDOWN):
        label = "1/298 s" if mode == "ptworun" else "298 s"
        key = h.toy_key(h.STUB_OPEN_SEMANTIC + [COUNT % label], "none", [[1, 0, ""]])
        self.assertEqual(self.found(mode, [[h.OPEN, BLANK]], 1, declaration), [
            ("noop-tap-effect", "error", h.finding_id("noop-tap-effect", ["noop", key, BLANK]),
             {"word": BLANK, "changed": changed})])

    def test_a_declared_restart_is_refused_and_reported_once_per_state_and_node(self):
        """The complement tap and the root tap both restart the countdown 298 -> 300 from the open state: both are
        refused (no noop-tap-effect), and only the first is reported."""
        summary = self.tmp / "s.json"
        self.assertEqual(self.found("pcount", [[h.OPEN, BLANK], [h.OPEN, SCREEN]], 0, summary=summary), [
            ("ambient-restart", "info", h.finding_id("ambient-restart", ["restart", OPEN_KEY, BLANK]), RESTART)])
        events = json.loads(summary.read_text())["events"]
        for word in (BLANK, SCREEN):
            self.assertEqual(events[word], {"accepted_states": 0, "refused_states": 1, "missed_states": 0})

    def test_the_same_restart_without_the_declaration_is_noop_tap_effect(self):
        self.noop("pcount", ["patches", "semantic", "frame"], declaration="")

    def test_a_countdown_that_skips_forward_is_noop_tap_effect(self):
        self.noop("pskip", ["patches", "semantic", "frame"])

    def test_a_restart_with_another_nodes_patch_is_noop_tap_effect(self):
        self.noop("pplus", ["patches", "semantic", "frame"])

    def test_a_restart_on_a_node_of_another_role_is_noop_tap_effect(self):
        self.noop("pcount", ["patches", "semantic", "frame"], declaration=COUNTDOWN.replace('"countdown"', '"timer"'))

    def test_two_digit_runs_or_changed_text_around_the_digits_are_noop_tap_effect(self):
        for mode in ("ptworun", "ptext"):
            with self.subTest(mode=mode):
                self.noop(mode, ["patches", "semantic", "frame"])

    def test_a_new_node_a_flag_change_another_frame_record_or_a_life_line_is_noop_tap_effect(self):
        for mode in ("pnode", "pflag", "pframe", "plife"):
            with self.subTest(mode=mode):
                self.noop(mode, ["patches", "semantic", "frame"])

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
            ("ambient-restart", h.finding_id("ambient-restart", ["restart", PRESSED_KEY, BUTTON]),
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


class RuleTest(h.ExploreCase):
    """The parts of the rule one at a time, on snapshots (no probe)."""

    BEFORE = {"semantic": [COUNT % "298 s"], "frame": ["frame\t4\t2\t1", "label\t2\t-\t16\t0\t0\t0\t0\t1\t40\t16\t40\t16"
                                                       "\t=298 s\t-"], "life": [], "due": None, "env": []}

    def after(self, label="300 s", frame_text=None, life=()):
        text = label if frame_text is None else frame_text
        return {"semantic": [COUNT % label], "frame": ["frame\t4\t2\t2", "label\t2\t-\t16\t0\t0\t0\t0\t1\t40\t16\t40"
                                                       "\t16\t=%s\t-" % text], "life": list(life), "due": None, "env": []}

    @staticmethod
    def patch(old="298 s", new="300 s", op="update", field="text", key="count"):
        line = "\t".join((op, key, field, old, new))
        return g.parse_record("patches", line)

    def declared(self, patches, after, changed=("patches", "semantic", "frame"), frame=True):
        return r.declared(patches, self.BEFORE, after, list(changed), frame, "countdown")

    def test_forward(self):
        self.assertEqual(r.forward(b"298 s", b"300 s"), (298, 300))
        self.assertEqual(r.forward(b"300 s", b"300 s"), (300, 300))
        for old, new in ((b"300 s", b"298 s"), (b"1/298 s", b"1/300 s"), (b"298 s", b"300 sec"), (b"s", b"s"),
                         (b"298 s", b"x300 s")):
            with self.subTest(old=old, new=new):
                self.assertIsNone(r.forward(old, new))

    def test_each_condition(self):
        restart = [{"node": "count", "old": 298, "new": 300}]
        self.assertEqual(self.declared([self.patch()], self.after()), restart)
        self.assertEqual(self.declared([self.patch()], self.after(frame_text="x"), frame=False), restart)
        for name, patches, after, changed in (
                ("no patch", [], self.after(), ("semantic",)),
                ("a set patch", [self.patch(op="set")], self.after(), ("patches", "semantic", "frame")),
                ("another field", [self.patch(field="hidden")], self.after(), ("patches", "semantic", "frame")),
                ("another key", [self.patch(key="title")], self.after(), ("patches", "semantic", "frame")),
                ("a backward patch", [self.patch("300 s", "298 s")], self.after(), ("patches", "semantic", "frame")),
                ("a backward label", [self.patch()], self.after("290 s"), ("patches", "semantic", "frame")),
                ("a trace record", [self.patch()], self.after(), ("patches", "trace", "semantic", "frame")),
                ("a deadline", [self.patch()], self.after(), ("patches", "semantic", "due", "frame")),
                ("env", [self.patch()], self.after(), ("patches", "semantic", "env", "frame")),
                ("a frame label not the node's", [self.patch()], self.after(frame_text="301 s"),
                 ("patches", "semantic", "frame")),
                ("a life line", [self.patch()], self.after(life=["life\t1\tcreated\t0\t-1\t0\t=x"]),
                 ("patches", "semantic", "frame"))):
            with self.subTest(name=name):
                self.assertIsNone(self.declared(patches, after, changed))
