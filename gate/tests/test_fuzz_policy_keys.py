"""T129: one policy with `fuzz`, `fuzz_runs` and `profile` is read by every reader of `policy.toml`, and the `parser`
profile alone makes a module a required fuzz target."""

from rigor_lib import facts_policy, fuzz_gate, grade_policy, perf_policy, policy_check, witness_scope
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase

POLICY = '''[global]
deny = ["kill"]

[module."//p:parse"]
level = "L3"
impl = ["p/parse.c"]
exports = ["parse_run"]
fuzz = true
fuzz_runs = 5000
profile = ["parser"]

[module."//p:lex"]
level = "L2"
impl = ["p/lex.c"]
profile = "parser"
fuzz_runs = 7

[module."//p:plain"]
level = "L2"
impl = ["p/plain.c"]
'''


class EveryReader(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.path = str(self.tmp / "policy.toml")
        (self.tmp / "policy.toml").write_text(POLICY)

    def test_facts_policy_accepts_the_three_keys(self):
        policy = facts_policy.load_policy(self.path)
        self.assertEqual(sorted(policy.modules), ["//p:lex", "//p:parse", "//p:plain"])

    def test_grade_policy_readers(self):
        self.assertEqual(grade_policy.load_levels(self.path),
                         {"//p:parse": "L3", "//p:lex": "L2", "//p:plain": "L2"})
        document = grade_policy.load_document(self.path)
        self.assertEqual(document["module"]["//p:parse"]["fuzz_runs"], 5000)

    def test_the_witness_and_perf_readers(self):
        document = grade_policy.load_document(self.path)
        mapping, _ = witness_scope.impl_map(document, grade_policy.load_levels(self.path))
        self.assertEqual(sorted(mapping), ["//p:lex", "//p:parse", "//p:plain"])
        self.assertEqual(perf_policy.from_policy(self.path), [])

    def test_the_profile_reader(self):
        document = grade_policy.load_document(self.path)
        self.assertEqual(policy_check.declared_profiles("//p:parse", document["module"]["//p:parse"]), ("parser",))
        self.assertEqual(policy_check.declared_profiles("//p:lex", document["module"]["//p:lex"]), ("parser",))

    def test_the_fuzz_reader_requires_fuzz_true_or_the_parser_profile(self):
        self.assertEqual(fuzz_gate.load_policy(self.path), {"//p:parse": 5000, "//p:lex": 7})

    def test_the_parser_profile_alone_uses_the_default_budget(self):
        (self.tmp / "p2.toml").write_text('[module."//p:lex"]\nprofile = ["pure", "parser"]\n')
        self.assertEqual(fuzz_gate.load_policy(str(self.tmp / "p2.toml")), {"//p:lex": fuzz_gate.DEFAULT_RUNS})

    def test_fuzz_runs_without_fuzz_or_the_parser_profile_is_exit_2(self):
        (self.tmp / "p3.toml").write_text('[module."//p:lex"]\nprofile = ["pure"]\nfuzz_runs = 5\n')
        with self.assertRaises(InternalError):
            fuzz_gate.load_policy(str(self.tmp / "p3.toml"))
        (self.tmp / "p4.toml").write_text('[module."//p:lex"]\nfuzz = false\nprofile = "parser"\n')
        self.assertEqual(fuzz_gate.load_policy(str(self.tmp / "p4.toml")), {"//p:lex": fuzz_gate.DEFAULT_RUNS})

    def test_a_module_without_either_is_not_required(self):
        (self.tmp / "p5.toml").write_text('[module."//p:lex"]\nprofile = ["pure"]\n')
        self.assertEqual(fuzz_gate.load_policy(str(self.tmp / "p5.toml")), {})
