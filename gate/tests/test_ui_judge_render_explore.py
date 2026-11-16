"""The explorer's side of the `ui-render` judge (U07, docs/ui-judges-render.md, "Ink per new state"): the ink plan,
the ink step (the re-taken frame, `ink_moved`, the error pseudo step), the input after a moved ink, and the refusal of
a probe without `ink`."""

import unittest
from types import SimpleNamespace

from rigor_lib.ui_explore_grammar import FRAME_FIELDS, INK_FIELDS, parse_record, parse_typed_line
from rigor_lib.ui_explore_probe import ProbeError
from rigor_lib.ui_explore_catalogue import load as load_catalogue
from rigor_lib.ui_explore_key import key_hash, projection
from rigor_lib.ui_explore_run import InkPlan, Run, Step, base_key, before_inputs, ink_step
from rigor_lib.ui_explore_words import inputs
from tests.helpers import TempDirTestCase, run_rigor
from tests.test_ui_explore_helpers import STUB_OPEN_SEMANTIC, TOY
from tests.test_ui_judge_helpers import CANARY_CONTRACT


def frame_of(crc, extra=()):
    return tuple(parse_typed_line(FRAME_FIELDS, line) for line in ["lvprobe\t1\t0", "frame\t320\t240\t" + crc]
                 + list(extra))


def stepped(index, key, crc):
    item = Step(index, "w", key=key)
    item.obs["frame"] = frame_of(crc)
    return item


INK_OK = (parse_typed_line(INK_FIELDS, "ink\t1\t5\t0,0,1,1\t000000\t000000\tffffff\tffffff"),)
NOINK = (parse_typed_line(INK_FIELDS, "noink\t1\tunstable"),)


class InkPlanTest(unittest.TestCase):
    def inked(self, plan, item, records=INK_OK, moved=False):
        wanted = plan.wants(item)
        if wanted:
            item.obs.update(ink=records, ink_moved=moved)
            plan.record(item)
        return wanted

    def test_each_key_and_checksum_is_inked_once_when_usable_and_retried_once_when_not(self):
        plan = InkPlan()
        self.assertEqual([self.inked(plan, stepped(i, k, c)) for i, (k, c) in
                          enumerate([("a", "c1"), ("b", "c1"), ("a", "c1"), ("a", "c2"), ("a", "c2")])],
                         [True, True, False, True, False])
        self.assertEqual([self.inked(plan, stepped(0, "m", "c1"), moved=True) for _ in range(3)], [True, True, False])
        self.assertEqual([self.inked(plan, stepped(0, "n", "c1"), records=NOINK) for _ in range(3)],
                         [True, True, False])

    def test_at_most_four_checksums_per_key_then_capped(self):
        plan = InkPlan()
        self.assertEqual([self.inked(plan, stepped(i, "d", "c%d" % i)) for i in range(6)],
                         [True, True, True, True, False, False])
        self.assertEqual(plan.capped, ["d"])
        self.assertTrue(self.inked(plan, stepped(0, "d", "c1")) is False)     # an inked checksum stays done

    def test_the_second_run_tries_exactly_the_steps_the_first_tried(self):
        run = Run([], [stepped(i, "k%d" % i, "c") for i in range(3)])
        run.inked = [0, 2]
        again = InkPlan.again(run)
        self.assertEqual([again.wants(item) for item in run.steps], [True, False, True])


class FakeSession:
    def __init__(self, records, frame, error=None):
        self.ink_records, self.frame_records, self.error, self.frames = records, frame, error, 0

    def ink(self):
        if self.error is not None:
            raise self.error
        return self.ink_records

    def frame(self):
        self.frames += 1
        return self.frame_records


class InkStepTest(unittest.TestCase):
    def test_the_frame_is_taken_again_and_compared_without_its_life_and_taps_lines(self):
        for again, moved in ((frame_of("c1"), False), (frame_of("c1", ["taps\tprobe"]), False),
                             (frame_of("c2"), True)):
            item, plan = stepped(0, "k", "c1"), InkPlan()
            run, session = Run(["w"], [item]), FakeSession(INK_OK, again)
            self.assertTrue(ink_step(session, run, item, plan))
            self.assertEqual((item.obs["ink"], item.obs["ink_moved"], session.frames, run.inked),
                             (INK_OK, moved, 1, [0]))
            self.assertEqual((("k", "c1") in plan.done), not moved)

    def test_an_ink_error_ends_the_run_in_a_pseudo_step_and_the_second_run_tries_it_too(self):
        item = stepped(0, "k", "c1")
        run = Run(["w"], [item])
        error = ProbeError("protocol", "ink", "err ink internal")
        self.assertFalse(ink_step(FakeSession(INK_OK, frame_of("c1"), error), run, item, InkPlan()))
        self.assertEqual(([s.word for s in run.steps], run.error[0], "ink" in item.obs, run.inked),
                         (["w", "ink"], 1, False, [0]))
        self.assertTrue(InkPlan.again(run).wants(item))

    def test_after_a_moved_ink_an_input_compares_against_a_fresh_snapshot(self):
        """The step before moved under its ink: the probe's frame is the re-taken one (B, not the step's A). A
        complement tap that changes nothing is `refused`; compared with the stale A it would be a false
        noop-tap-effect."""
        class TapSession(FakeSession):
            now = 0

            def records(self, name):
                return ()

            def next_due(self):
                return None

            def env_inputs(self):
                return ()

            def hit_test(self, x, y):
                return None

            def tap(self, x, y):
                return (None, None)
        tap = SimpleNamespace(cls="u3", spec=(), get={"x": 5, "y": 5}.get)
        for moved, want in ((True, ("refused", None)), (False, ("ok", ["frame"]))):
            before = stepped(0, "k", "a")
            before.obs.update(semantic=(), due=None, env=(), ink_moved=moved)
            item = Step(1, "tap")
            inputs(TapSession(INK_OK, frame_of("b")), item, before_inputs(before), [("tap", tap)], None)
            self.assertEqual((item.applies[-1], item.noop and item.noop["changed"]), want)

    def test_after_a_moved_ink_wait_change_leaves_the_key_of_a_fresh_observation(self):
        catalogue = load_catalogue(TOY)
        fresh = (parse_record("semantic", STUB_OPEN_SEMANTIC[0]),)

        class KeySession:
            now = 1000

            def records(self, name):
                return fresh

            def next_due(self):
                return None

            def env_inputs(self):
                return ()
        want = key_hash(projection({"semantic": fresh, "due": None, "env": ()}, 1000, catalogue.key))
        for moved, expected in ((True, want), (False, "stale")):
            before = stepped(0, "stale", "a")
            before.obs["ink_moved"] = moved
            item = Step(1, "wait-change", key_before="stale")
            self.assertEqual(base_key(KeySession(), item, before, catalogue), expected)
        self.assertNotEqual(want, "stale")

    def test_no_plan_or_an_unwanted_step_takes_no_ink(self):
        item = stepped(0, "k", "c1")
        session = FakeSession(INK_OK, frame_of("c1"))
        self.assertTrue(ink_step(session, Run(["w"], [item]), item, None))
        self.assertEqual((session.frames, "ink" in item.obs), (0, False))


class NeedsInkTest(TempDirTestCase):
    def test_ui_render_refuses_a_probe_without_ink(self):
        probe = self.tmp / "no-ink"
        probe.write_text("#!/bin/sh\necho 'ui-probe/1 ready frame-facts'\nexec cat >/dev/null\n")
        probe.chmod(0o755)
        done = run_rigor(["ui-explore", "--probe", probe, "--catalogue", TOY, "--strategy", "sweep",
                          "--origin-ms", "1000", "--seed", "7", "--judges", "ui-render", "--contract", CANARY_CONTRACT,
                          "--today", "2026-11-16", "--out", self.tmp / "out.json"])
        self.assertEqual(done.code, 2, done.stderr)
        self.assertIn("ui-render needs a probe that announces ink", done.stderr)


if __name__ == "__main__":
    unittest.main()
