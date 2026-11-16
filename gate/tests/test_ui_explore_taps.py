"""The probe protocol as the C probe speaks it since U05a (docs/ui-model.md): the full capability greeting, frame-facts
records parsed by type and field count, `hit-test`, `tap` (u2 probe taps, u3 complement taps), `crop` and its evidence
image, `ink`, `ok apply missed`, and the err reasons `no-frame` and `too-large` ending the run. Against the stub probe's
frame-facts modes (gate/tests/data/ui_explore/stub_probe.py)."""

import struct
import zlib

from rigor_lib import ui_explore_catalogue as catalogue_mod
from rigor_lib import ui_explore_probe as up
from tests import test_ui_explore_helpers as h
from tests.helpers import TempDirTestCase

PRESS, BUTTON, BLANK, SCREEN, CREATE, EMPTY = "tap-press", "probe-btn", "probe-blank", "probe-screen", "create", "code-empty"
TAPS = ('[u2]\nevents = []\n\n[u3]\nevents = []',
        '[u2]\nevents = [ { id = "probe-btn", x = 0, y = 0, target = "lv_button" },\n'
        '  { id = "probe-screen", x = 3, y = 1, target = "lv_button" } ]\n\n'
        '[u3]\nevents = [ { id = "probe-blank", x = 3, y = 1 } ]')
PRESS_LINE = '{ id = "tap-press", intent = 1, arg = 0, expect = "accept" },'
CREATE_LINE = PRESS_LINE + '\n  { id = "create", intent = 7, arg = 0, expect = "accept" },'
AFTER = ["title\tlabel\tToy\t8\t8\t24\t16\t1\t-\t-\tbody\tnormal\tnone\tnone",
         "button\tbutton\tPress\t8\t40\t100\t36\t1\t1:0\t-\tbody\tnormal\ttap\tnone",
         "notice\tlabel\tPressed\t8\t90\t56\t16\t1\t-\t-\tbody\tnormal\tnone\tnone"]
PRESSED_KEY = h.toy_key(AFTER, "pending", [])


def tearDownModule():
    h.assert_no_stubs()


class SessionTest(TempDirTestCase):
    def session(self, mode):
        session = up.Session([str(h.stub(self.tmp, mode))], 2.0, up.Budget(60))
        self.addCleanup(session.close)
        return session

    def test_the_full_greeting_and_every_new_command(self):
        session = self.session("facts")
        self.assertEqual(session.caps, ("frame-facts", "ink", "hit-test", "tap", "apply-missed", "crop"))
        session.open(1000, 7)
        frame = session.frame()
        self.assertEqual([r.fields[0] for r in frame], ["lvprobe", "frame", "node", "region", "node", "region", "life"])
        self.assertEqual(frame[-1].values[-1], b"=lv_\x01obj")
        self.assertEqual([r.fields[0] for r in session.frame()][-1], "region")   # a life line is in one frame only
        self.assertEqual((session.hit_test(0, 0), session.hit_test(3, 1)), (1, 0))
        self.assertEqual(session.tap(0, 0), (1, 1))
        self.assertEqual(session.crop(1, 0, 2, 2), bytes.fromhex("2196f3ffffffffff") * 2)
        self.assertEqual([r.fields[0] for r in session.ink()], ["ink", "noink"])
        self.assertEqual(session.apply(3, 1, 0, ""), "missed")
        session.quit()

    def test_blocked_replies(self):
        session = self.session("tapblocked")
        session.open(1000, 7)
        self.assertEqual((session.hit_test(0, 0), session.tap(0, 0)), ("blocked", "blocked"))

    def test_greetings_out_of_order_or_repeated_are_protocol_errors(self):
        for mode in ("badorder", "dupcap"):
            with self.subTest(mode=mode):
                with self.assertRaises(up.ProbeError) as caught:
                    self.session(mode)
                self.assertEqual((caught.exception.kind, caught.exception.command, caught.exception.detail),
                                 ("protocol", "greeting", "unknown, repeated or unordered capabilities"))


class TapExploreTest(h.ExploreCase):
    def taps(self):
        return self.catalogue(PRESS_LINE, CREATE_LINE, base=self.catalogue(*TAPS))

    def test_a_probe_tap_that_presses_the_button_is_accepted_and_a_complement_tap_is_refused(self):
        summary = self.tmp / "s.json"
        _, found = self.replay("facts", [[h.OPEN, BUTTON], [h.OPEN, BLANK]], "--summary", str(summary),
                               catalogue=self.taps(), code=0)
        self.assertEqual(found, [])
        events = __import__("json").loads(summary.read_text())["events"]
        self.assertEqual(events[BUTTON], {"accepted_states": 1, "refused_states": 0, "missed_states": 0})
        self.assertEqual(events[BLANK], {"accepted_states": 0, "refused_states": 1, "missed_states": 0})

    def test_the_canary_a_tap_under_the_notice_is_missed_with_the_nodes_image(self):
        _, found = self.replay("facts", [[h.OPEN, PRESS, BUTTON], [h.OPEN, PRESS, PRESS]], "--evidence",
                               str(self.tmp / "ev"), catalogue=self.taps(), code=1)
        self.assertEqual([(f["id"], f["observed"], f["path"]) for f in found], sorted([
            (h.finding_id("intent-missed", ["missed", PRESSED_KEY, BUTTON]), {"word": BUTTON, "applies": ["missed"]},
             [h.OPEN, PRESS, BUTTON]),
            (h.finding_id("intent-missed", ["missed", PRESSED_KEY, PRESS]), {"word": PRESS, "applies": ["missed"]},
             [h.OPEN, PRESS, PRESS])]))
        tap = [f for f in found if f["observed"]["word"] == BUTTON][0]
        name = tap["id"].rsplit("/", 1)[1]
        self.assertEqual(tap["evidence"], [name + "/paths.json", name + "/tap-node.png"])
        data = (self.tmp / "ev" / name / "tap-node.png").read_bytes()
        self.assertEqual(struct.unpack(">II", data[16:24]), (2, 2))
        self.assertEqual(zlib.decompress(data[41:-16]), (b"\x00" + bytes.fromhex("2196f3ff") * 2) * 2)
        press = [f for f in found if f["observed"]["word"] == PRESS][0]
        self.assertEqual(press["evidence"], [press["id"].rsplit("/", 1)[1] + "/paths.json"])
        _, again = self.replay("facts", [tap["path"]], catalogue=self.taps(), code=1)
        self.assertEqual([f["id"] for f in again], [tap["id"]])

    def probe_error(self, mode, words, observed, before):
        _, found = self.replay(mode, [words], catalogue=self.taps(), code=1)
        ident = h.finding_id("probe-internal-error", [observed["kind"], observed["command"], before, words[-1]])
        self.assertEqual([(f["check"], f["id"], f["observed"]) for f in found],
                         [("probe-internal-error", ident, observed)])

    def test_a_complement_tap_that_changes_the_model_is_a_product_finding_and_the_run_goes_on(self):
        _, found = self.replay("blankchange", [[h.OPEN, BLANK, PRESS]], catalogue=self.taps(), code=1)
        self.assertEqual([(f["id"], f["observed"], f["path"]) for f in found],
                         [(h.finding_id("noop-tap-effect", ["noop", h.STUB_OPEN_KEY, BLANK]),
                           {"word": BLANK, "changed": ["trace"]}, [h.OPEN, BLANK])])

    def test_a_tap_on_a_screen_root_pressed_nothing(self):
        summary = self.tmp / "s.json"
        _, found = self.replay("facts", [[h.OPEN, SCREEN]], "--summary", str(summary), catalogue=self.taps(), code=0)
        self.assertEqual(found, [])
        data = __import__("json").loads(summary.read_text())
        self.assertEqual(data["events"][SCREEN], {"accepted_states": 0, "refused_states": 1, "missed_states": 0})
        self.assertEqual(data["outcomes"][SCREEN], {"pressed lv_obj 0,0,3,1 root": 1, "tap refused": 1})

    def test_a_tap_that_another_node_takes_is_misrouted_with_the_image(self):
        _, found = self.replay("misroute", [[h.OPEN, BUTTON]], "--evidence", str(self.tmp / "ev"),
                               catalogue=self.taps(), code=1)
        self.assertEqual(sorted((f["check"], f["id"]) for f in found), sorted([
            ("tap-misrouted", h.finding_id("tap-misrouted", ["misrouted", h.STUB_OPEN_KEY, BUTTON])),
            ("intent-missed", h.finding_id("intent-missed", ["missed", h.STUB_OPEN_KEY, BUTTON]))]))
        misrouted = [f for f in found if f["check"] == "tap-misrouted"][0]
        self.assertEqual(misrouted["observed"], {"word": BUTTON,
                                                 "pressed": {"index": 2, "class": "lv_obj", "box": [0, 0, 3, 1]},
                                                 "aimed": {"index": 1, "class": "lv_button", "box": [0, 0, 1, 1]}})
        name = misrouted["id"].rsplit("/", 1)[1]
        self.assertEqual(misrouted["evidence"], [name + "/paths.json", name + "/tap-node.png"])

    def test_the_effect_of_work_the_frame_runs_is_seen(self):
        _, found = self.replay("framework", [[h.OPEN, BUTTON]], catalogue=self.taps(), code=0)
        self.assertEqual(found, [])

    def test_life_lines_are_not_a_change_but_a_new_one_after_a_refused_input_is(self):
        _, found = self.replay("facts", [[h.OPEN, CREATE, EMPTY]], catalogue=self.taps(), code=0)
        self.assertEqual(found, [])
        self.probe_error("refuselife", [h.OPEN, EMPTY], {"kind": "contract", "command": "apply", "step": 1,
                         "detail": "a refused input changed the model: frame"}, h.STUB_OPEN_KEY)

    def test_a_wide_node_is_banded_and_its_image_capped(self):
        _, found = self.replay("wide", [[h.OPEN, PRESS, BUTTON]], "--evidence", str(self.tmp / "ev"),
                               catalogue=self.taps(), code=1)
        tap = [f for f in found if f["observed"]["word"] == BUTTON][0]
        data = (self.tmp / "ev" / tap["id"].rsplit("/", 1)[1] / "tap-node.png").read_bytes()
        self.assertEqual(struct.unpack(">II", data[16:24]), (256, 2))

    def test_numbers_of_frame_records_and_a_tap_that_clicked_what_it_did_not_press(self):
        self.probe_error("framenum", [h.OPEN], {"kind": "protocol", "command": "frame", "step": 0,
                         "detail": "a node record whose field 1 is not a number of its kind"}, None)
        self.setUp()
        self.probe_error("tapnone", [h.OPEN, BUTTON], {"kind": "protocol", "command": "tap", "step": 1,
                         "detail": "a tap that clicked a node it did not press"}, h.STUB_OPEN_KEY)

    def test_a_catalogue_can_require_capabilities(self):
        catalogue = self.catalogue('drain_ms = 1024', 'drain_ms = 1024\nrequires = ["tap", "crop"]')
        outcome, _ = self.replay("good", [[h.OPEN]], catalogue=catalogue, code=2)
        self.assertIn("the catalogue requires the probe capabilities tap, crop, which the probe does not announce",
                      outcome.stderr)
        self.replay("facts", [[h.OPEN]], catalogue=catalogue, code=0)
        for bad in ('["teleport"]', '["tap", "tap"]', '"tap"'):
            with self.subTest(bad=bad):
                broken = self.catalogue('drain_ms = 1024', 'drain_ms = 1024\nrequires = %s' % bad)
                outcome, _ = self.replay("facts", [[h.OPEN]], catalogue=broken, code=2)
                self.assertIn("requires: must be a list of distinct probe capabilities", outcome.stderr)

    def test_a_catalogue_can_require_the_pointer_capability(self):
        """U05c: `requires` accepts `pointer` (in any position: it is normalised to the greeting's order); the stub probe,
        like a probe of a product without a pointer entry, does not announce it: the house message, exit 2."""
        catalogue = self.catalogue('drain_ms = 1024', 'drain_ms = 1024\nrequires = ["pointer", "tap"]')
        self.assertEqual(catalogue_mod.loads(catalogue.read_bytes()).requires, ("tap", "pointer"))
        outcome, _ = self.replay("facts", [[h.OPEN]], catalogue=catalogue, code=2)
        self.assertIn("the catalogue requires the probe capabilities pointer, which the probe does not announce",
                      outcome.stderr)
        twice = self.catalogue('drain_ms = 1024', 'drain_ms = 1024\nrequires = ["pointer", "pointer"]')
        outcome, _ = self.replay("facts", [[h.OPEN]], catalogue=twice, code=2)
        self.assertIn("requires: must be a list of distinct probe capabilities (frame-facts, ink, hit-test, tap, "
                      "apply-missed, crop, pointer)", outcome.stderr)

    def test_a_tap_that_presses_another_node_than_the_hit_query(self):
        self.probe_error("tapdisagree", [h.OPEN, BUTTON], {"kind": "contract", "command": "tap", "step": 1,
                         "detail": "the tap pressed another node than the hit query found"}, h.STUB_OPEN_KEY)

    def test_a_blocked_tap_is_refused_and_checked(self):
        summary = self.tmp / "s.json"
        _, found = self.replay("tapblocked", [[h.OPEN, BUTTON]], "--summary", str(summary), catalogue=self.taps(),
                               code=0)
        self.assertEqual(found, [])
        self.assertEqual(__import__("json").loads(summary.read_text())["events"][BUTTON],
                         {"accepted_states": 0, "refused_states": 1, "missed_states": 0})

    def test_frame_records_by_type_and_field_count(self):
        for mode, detail in (("framebad", "a node record with 20 fields, wanted 21"),
                             ("frametype", "a record of a type this reply does not have")):
            with self.subTest(mode=mode):
                self.setUp()
                self.probe_error(mode, [h.OPEN], {"kind": "protocol", "command": "frame", "step": 0, "detail": detail},
                                 None)

    def test_a_crop_of_the_wrong_shape_adds_its_finding_and_the_first_stands(self):
        _, found = self.replay("cropbad", [[h.OPEN, PRESS, BUTTON]], catalogue=self.taps(), code=1)
        tap_key = [f for f in found if f["check"] == "intent-missed"][0]["state"]["key"]
        self.assertEqual(tap_key, PRESSED_KEY)
        after = h.toy_key(AFTER, "pending", [])
        self.assertEqual(sorted((f["check"], f["id"], f["observed"]) for f in found), sorted([
            ("intent-missed", h.finding_id("intent-missed", ["missed", PRESSED_KEY, BUTTON]),
             {"word": BUTTON, "applies": ["missed"]}),
            ("probe-internal-error", h.finding_id("probe-internal-error", ["protocol", "crop", after, "evidence"]),
             {"kind": "protocol", "command": "crop", "step": 3, "detail": "a crop that is not 2 rows of 16 hex digits"})]))

    def test_no_frame_and_too_large_end_the_run_and_nothing_follows(self):
        for mode, words, command, step in (("noframe", [h.OPEN, BUTTON], "hit-test", 1),
                                           ("toolarge", [h.OPEN], "frame", 0)):
            with self.subTest(mode=mode):
                self.setUp()
                log = self.tmp / ("%s.log" % mode)
                _, found = self.replay(mode, [words], catalogue=self.taps(), code=1, log=log)
                self.assertEqual([(f["observed"]["kind"], f["observed"]["command"], f["observed"]["detail"],
                                   f["observed"]["step"]) for f in found], [("protocol", command, "an err reply", step)])
                runs = log.read_text().split("domain-count\n")[1:]
                self.assertEqual(len(runs), 2)
                self.assertTrue(all(run.rstrip("\n").rsplit("\n", 1)[-1].split(" ")[0] == command for run in runs),
                                "a command was sent after the poisoning err")


AMBIENT = ('drain_ms = 1024', 'drain_ms = 1024\nrequires = ["pointer"]\nambient = { trace = ["touch"], '
           'trace_provenance = "oracle:the stub posts touch on every tap"%s }')
RESTART = ', due_restart_ms = 5000, due_restart_provenance = "oracle:the stub restarts its idle deadline"'


class AmbientTest(h.ExploreCase):
    """U05c: taps through a product's pointer entry, whose entry posts `touch` on every sample (docs/ui-explore.md,
    "Ambient events")."""

    def ambient(self, restart=""):
        return self.catalogue(AMBIENT[0], AMBIENT[1] % restart, base=self.catalogue(PRESS_LINE, CREATE_LINE,
                                                                                     base=self.catalogue(*TAPS)))

    def found(self, mode, paths, code, restart="", summary=None):
        extra = ("--summary", str(summary)) if summary else ()
        _, found = self.replay(mode, paths, *extra, catalogue=self.ambient(restart), code=code)
        return [(f["check"], f["id"], f["observed"]) for f in found]

    def test_the_ambient_touch_is_not_a_change(self):
        """A button tap is accepted, a complement tap changes nothing, and the canary under the notice is missed again,
        although every tap posted `touch`."""
        summary = self.tmp / "s.json"
        self.assertEqual(self.found("ptouch", [[h.OPEN, BUTTON], [h.OPEN, BLANK]], 0, summary=summary), [])
        data = __import__("json").loads(summary.read_text())
        self.assertEqual((data["events"][BLANK], data["taps"]),
                         ({"accepted_states": 0, "refused_states": 1, "missed_states": 0}, "entry"))
        self.assertEqual(self.found("ptouch", [[h.OPEN, PRESS, BUTTON]], 1), [
            ("intent-missed", h.finding_id("intent-missed", ["missed", PRESSED_KEY, BUTTON]),
             {"word": BUTTON, "applies": ["missed"]})])

    def test_a_tap_without_its_touch_is_ambient_missing(self):
        self.assertEqual(self.found("pnotouch", [[h.OPEN, BLANK]], 1), [
            ("ambient-missing", h.finding_id("ambient-missing", ["missing", h.STUB_OPEN_KEY, BLANK]),
             {"word": BLANK, "types": ["touch"]})])

    def test_a_tap_with_two_touches_is_ambient_extra_and_the_second_is_a_change(self):
        found = self.found("ptwice", [[h.OPEN, BLANK]], 1)
        self.assertEqual(sorted(found), sorted([
            ("ambient-extra", h.finding_id("ambient-extra", ["extra", h.STUB_OPEN_KEY, BLANK]),
             {"word": BLANK, "types": ["touch"]}),
            ("noop-tap-effect", h.finding_id("noop-tap-effect", ["noop", h.STUB_OPEN_KEY, BLANK]),
             {"word": BLANK, "changed": ["trace"]})]))

    def test_a_complement_tap_that_posts_touch_and_changes_the_scene_is_still_noop_tap_effect(self):
        self.assertEqual(self.found("pchange", [[h.OPEN, BLANK]], 1), [
            ("noop-tap-effect", h.finding_id("noop-tap-effect", ["noop", h.STUB_OPEN_KEY, BLANK]),
             {"word": BLANK, "changed": ["patches"]})])

    def test_a_restarted_idle_deadline_is_no_change_only_when_declared(self):
        # one frame first, so that the restarted deadline (tap + 5000) is not the one armed at open (open + 5000)
        self.assertEqual(self.found("prestart", [[h.OPEN, "one-frame", BLANK]], 0, restart=RESTART), [])
        found = self.found("prestart", [[h.OPEN, "one-frame", BLANK]], 1)
        self.assertEqual([(c, o) for c, _, o in found], [("noop-tap-effect", {"word": BLANK, "changed": ["due"]})])

    def test_ambient_types_outside_taps_and_at_another_instant_are_ordinary(self):
        """`touch` is discounted in a tap step only: the same record type from an apply is a change as before."""
        from rigor_lib import ui_explore_grammar as g
        from rigor_lib import ui_explore_words as w
        records = [g.Record("0\ttouch\t5", ("0", "touch", "5"), ()), g.Record("1\ttouch\t4", ("1", "touch", "4"), ()),
                   g.Record("2\ttouch\t5", ("2", "touch", "5"), ()), g.Record("3\tpress\t5", ("3", "press", "5"), ())]
        other, missing, extra = w.ambient_split(records, ("touch", "beep"), 5)
        self.assertEqual(([r.raw for r in other], missing, extra), (["1\ttouch\t4", "2\ttouch\t5", "3\tpress\t5"],
                                                                     ["beep"], ["touch"]))

    def test_taps_injected_at_a_product_indev_are_reported_once(self):
        summary = self.tmp / "s.json"
        _, found = self.replay("pindev", [[h.OPEN, BUTTON], [h.OPEN, BLANK]], "--summary", str(summary),
                               catalogue=self.catalogue(PRESS_LINE, CREATE_LINE, base=self.catalogue(*TAPS)), code=0)
        sha = catalogue_mod.load(self.tmp / sorted(p.name for p in self.tmp.glob("cat*.toml"))[-1]).sha256
        self.assertEqual([(f["check"], f["severity"], f["id"], f["observed"]) for f in found],
                         [("taps-injected", "info", h.finding_id("taps-injected", ["taps-injected", sha]),
                           {"taps": "indev", "pointer": False})])
        self.assertEqual(__import__("json").loads(summary.read_text())["taps"], "indev")
        _, plain = self.replay("facts", [[h.OPEN, BUTTON]], "--summary", str(summary),
                               catalogue=self.catalogue(PRESS_LINE, CREATE_LINE, base=self.catalogue(*TAPS)), code=0)
        self.assertEqual((plain, __import__("json").loads(summary.read_text())["taps"]), ([], None))

    def test_the_ambient_table_is_strict(self):
        base = self.catalogue(PRESS_LINE, CREATE_LINE, base=self.catalogue(*TAPS))
        good = 'ambient = { trace = ["touch"], trace_provenance = "oracle:x" }'
        for text, why in (
                ('requires = ["tap"]\n' + good, "needs `requires` with \"pointer\""),
                ('requires = ["pointer"]\nambient = { trace = [], trace_provenance = "oracle:x" }', "ambient.trace"),
                ('requires = ["pointer"]\nambient = { trace = ["a", "a"], trace_provenance = "oracle:x" }', "ambient.trace"),
                ('requires = ["pointer"]\nambient = { trace = ["a b"], trace_provenance = "oracle:x" }', "ambient.trace"),
                ('requires = ["pointer"]\nambient = { trace = ["a"] }', "missing key(s) trace_provenance"),
                ('requires = ["pointer"]\nambient = { trace = ["a"], trace_provenance = "x" }', "provenance"),
                ('requires = ["pointer"]\nambient = { trace = ["a"], trace_provenance = "oracle:x", extra = 1 }',
                 "unknown key(s) extra"),
                ('requires = ["pointer"]\nambient = { trace = ["a"], trace_provenance = "oracle:x", due_restart_ms = 5 }',
                 "go together"),
                ('requires = ["pointer"]\nambient = { trace = ["a"], trace_provenance = "oracle:x", due_restart_ms = 0, '
                 'due_restart_provenance = "oracle:y" }', "ambient.due_restart_ms"),
                ('requires = ["pointer"]\nambient = 3', "must be a table")):
            with self.subTest(text=text):
                with self.assertRaises(Exception) as caught:
                    catalogue_mod.loads(base.read_text().replace("drain_ms = 1024", "drain_ms = 1024\n" + text).encode())
                self.assertIn(why, str(caught.exception))
        loaded = catalogue_mod.loads(base.read_text().replace(
            "drain_ms = 1024", "drain_ms = 1024\nrequires = [\"pointer\"]\n" + good[:-2] + RESTART + " }").encode())
        self.assertEqual((loaded.ambient, loaded.due_restart_ms), (("touch",), 5000))
