"""The library side of `rigor ui-explore`: the three judge kinds and their registration, frame-seam lines handed to
judges parsed, derived key facts, until-change as one event, and the cost of the starvation judge."""

import time
import unittest
from types import SimpleNamespace

from rigor_lib import ui_explore_catalogue as cat
from rigor_lib import ui_explore_coverage as cov
from rigor_lib import ui_explore_key as uk
from rigor_lib import ui_explore_strategies as st
from rigor_lib.ui_explore_grammar import parse_record
from rigor_lib.ui_explore_judges import make, starvation_judge
from rigor_lib.ui_explore_probe import Budget
from rigor_lib.ui_explore_run import Config, execute
from tests import test_ui_explore_helpers as h
from tests.helpers import TempDirTestCase

CATALOGUE = cat.load(h.TOY)


def config(probe, catalogue=CATALOGUE):
    return Config(str(probe), 2.0, catalogue, Budget(60), 32)


class JudgeInterfaceTest(TempDirTestCase):
    def test_step_run_and_exploration_judges(self):
        seen = {"steps": [], "runs": 0}

        def step_judge(step, path, contract):
            seen["steps"].append((step.index, step.word, len(path), contract))
            if step.word == "tap-press":
                return [make("ui-coverage-gap", ["custom", step.key], None, [s.word for s in path] + [step.word],
                             {"criterion": "custom"}, {"note.json": {"frame": [r.values for r in step.obs["frame"]]}})]
            return []

        def run_judge(first, second, contract):
            seen["runs"] += 1
            self.assertEqual(first.words, second.words)
            return []

        explorer = st.Explorer(config(h.stub(self.tmp, "framelines")), "the contract", 32, h.OPEN,
                               step_judges=[step_judge], run_judges=[run_judge])
        st.replay(explorer, [[h.OPEN, "tap-press"]])
        self.assertEqual(seen["runs"], 1)
        self.assertEqual(seen["steps"], [(0, h.OPEN, 0, "the contract"), (1, "tap-press", 1, "the contract")])
        custom = [f for f in explorer.all_findings() if f["observed"] == {"criterion": "custom"}]
        self.assertEqual(custom[0]["_evidence"]["note.json"]["frame"], [(b"obj", b"label", b"A\tB"), (b"crc", b"\x01ff")])
        evaluated, found = cov.CRITERIA["C8"](explorer.exploration, None)
        self.assertTrue(evaluated)
        self.assertEqual(len(found), 2 * len(CATALOGUE.events) - 1)     # tap-press is the one exercised pair
        self.assertEqual(sorted(cov.CRITERIA), ["C1", "C8"])
        self.assertEqual(sorted(explorer.exploration.edges)[0][1], "tap-press")


class KeyTest(unittest.TestCase):
    def obs(self, label, due=None):
        lines = [h.STUB_OPEN_SEMANTIC[0], h.STUB_OPEN_SEMANTIC[1],
                 "pad\tfield\t%s\t8\t90\t0\t16\t1\t-\t-\tbody\tnormal\tnone\tnone" % label]
        return {"semantic": tuple(parse_record("semantic", line) for line in lines), "due": due, "env": ()}

    def test_derived_facts(self):
        text = h.TOY.read_text().replace("derived = []", (
            'derived = [ { name = "pad-len", op = "bucket", node = "pad", field = "label", measure = "length", '
            'boundaries = [1, 6, 7] }, { name = "count-down", op = "bucket", node = "pad", field = "label", '
            'measure = "digits", boundaries = [1, 6] }, { name = "due-in", op = "bucket", model = "due-in-ms", '
            'boundaries = [17] }, { name = "buttons", op = "count", role = "button" }, { name = "pad", op = '
            '"presence", node = "pad" }, { name = "text", op = "select", role = "field", field = "label" } ]'))
        key = cat.loads(text.encode()).key
        facts = uk.projection(self.obs("in 12 s", 1010), 1000, key)["facts"]
        self.assertEqual({k: facts[k] for k in ("pad-len", "count-down", "due-in", "buttons", "pad", "text")},
                         {"pad-len": [3], "count-down": [2], "due-in": 0, "buttons": 1, "pad": True,
                          "text": ["in 12 s"]})
        self.assertEqual(uk.projection(self.obs(""), 1000, key)["facts"]["count-down"], ["none"])
        self.assertEqual(uk.projection(self.obs(""), 1000, key)["facts"]["due-in"], "none")
        # two countdown values in one bucket give one key when the label is not a key field
        coarse_text = h.TOY.read_text().replace('"role", "label", ', '"role", ').replace("derived = []", (
            'derived = [ { name = "count-down", op = "bucket", node = "pad", field = "label", measure = "digits", '
            'boundaries = [1, 6] } ]'))
        coarse = cat.loads(coarse_text.encode()).key
        a, b = uk.projection(self.obs("in 3 s"), 1000, coarse), uk.projection(self.obs("in 4 s"), 1000, coarse)
        self.assertEqual(uk.key_hash(a), uk.key_hash(b))
        self.assertNotEqual(uk.key_hash(a), uk.key_hash(uk.projection(self.obs("in 9 s"), 1000, coarse)))


class TimeWordTest(TempDirTestCase):
    def test_until_change_is_one_event_on_a_perpetual_tick(self):
        run = execute(config(h.stub(self.tmp, "tick")), [h.OPEN, "tap-press", "until-change", "settle"])
        self.assertIsNone(run.error)
        self.assertEqual(run.steps[2].outcome, ["changed 4000"])
        self.assertEqual(run.steps[3].outcome, ["fired 4250"])

    def test_the_settle_suffix_ends_after_one_tick(self):
        run = execute(config(h.stub(self.tmp, "tick")), [h.OPEN], settle=True)
        self.assertEqual(run.words, [h.OPEN, "settle"])


class CostTest(unittest.TestCase):
    def test_the_starvation_judge_is_linear(self):
        judge = starvation_judge(32, CATALOGUE.key)
        steps = [SimpleNamespace(streak=i % 31, word="settle", starved=False) for i in range(20000)]
        start = time.monotonic()
        for index, step in enumerate(steps):
            self.assertEqual(judge(step, steps[:0] if index == 0 else _Prefix(steps, index), None), [])
        self.assertLess(time.monotonic() - start, 2)


class _Prefix:
    """A path prefix the judge must not walk (it is O(1) unless it reports)."""

    def __init__(self, steps, end):
        self.steps, self.end = steps, end

    def __len__(self):
        return self.end

    def __iter__(self):
        raise AssertionError("the starvation judge walked the whole path")
