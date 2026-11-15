"""The probe protocol as the C probe speaks it since U05a (docs/ui-model.md): the full capability greeting, frame-facts
records parsed by type and field count, `hit-test`, `tap` (u2 probe taps, u3 complement taps), `crop` and its evidence
image, `ink`, `ok apply missed`, and the err reasons `no-frame` and `too-large` ending the run. Against the stub probe's
frame-facts modes (gate/tests/data/ui_explore/stub_probe.py)."""

import struct
import zlib

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
