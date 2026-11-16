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


def tearDownModule():
    h.assert_no_stubs()


def config(probe, catalogue=CATALOGUE):
    return Config(probe=str(probe), deadline_s=10.0, catalogue=catalogue, budget=Budget(60))


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

        explorer = st.Explorer(config(h.stub(self.tmp, "framelines")), "the contract", h.OPEN,
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


class CharactersAndSelectorsTest(unittest.TestCase):
    def test_length_counts_characters_and_selectors_match_escaped_keys(self):
        text = h.TOY.read_text().replace("derived = []", (
            'derived = [ { name = "len", op = "bucket", node = "p\\\\x01", field = "label", measure = "length", '
            'boundaries = [3, 4] } ]'))
        key = cat.loads(text.encode()).key
        line = "p\\x01\tfield\t\\xd0\\xa7\\xd0\\xb0\\xd0\\xbe\t0\t0\t0\t0\t1\t-\t-\tb\tn\tn\tn"
        obs = {"semantic": (parse_record("semantic", line),), "due": None, "env": ()}
        self.assertEqual(uk.projection(obs, 0, key)["facts"]["len"], [1])     # 3 characters (6 bytes)


class EvidenceNameTest(TempDirTestCase):
    def test_judge_evidence_names_are_checked(self):
        from rigor_lib import ui_explore
        from rigor_lib.errors import InternalError
        for bad in ("../x.json", "paths.json", "X.json", "a/b.json", "runs.txt"):
            item = make("ui-coverage-gap", ["x"], None, [h.OPEN], {"criterion": "x"}, {bad: {}})
            with self.assertRaises(InternalError, msg=bad):
                ui_explore._evidence([item], str(self.tmp / ("ev-" + bad.replace("/", "_"))), [])


class TimeWordTest(TempDirTestCase):
    def test_until_change_is_one_event_on_a_perpetual_tick(self):
        run = execute(config(h.stub(self.tmp, "tick")), [h.OPEN, "tap-press", "until-change", "settle"])
        self.assertIsNone(run.error)
        self.assertEqual(run.steps[2].outcome, ["changed 4000"])
        self.assertEqual(run.steps[3].outcome, ["fired 4250"])

    def test_the_settle_check_ends_on_a_perpetual_tick(self):
        # one starvation window (1024 ms) after the path: the ticks at 1250, 1500, 1750 and 2000; the next is outside
        run = execute(config(h.stub(self.tmp, "tick")), [h.OPEN], settle=True)
        self.assertEqual(run.words, [h.OPEN] + ["settle"] * 4)
        self.assertFalse(run.starved)


class CostTest(unittest.TestCase):
    def test_the_starvation_judge_is_linear(self):
        judge = starvation_judge(CATALOGUE.key)
        steps = [SimpleNamespace(word="settle", starved=None) for i in range(20000)]
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
