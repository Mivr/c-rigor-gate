"""`rigor policy-check` (T127): findings on hand-made facts, the policy key in every reader, exit codes."""

import json
import os
import unittest

from rigor_lib import facts_data, facts_policy, facts_third_party, grade_policy, layering, policy_check, structure_data
from rigor_lib.errors import InternalError
from rigor_lib.cli import main
from tests.helpers import TempDirTestCase

P = "//p:"
THIRD = facts_third_party.ThirdParty(frozenset(), ("mbedtls_",))


def mod(name, deps=(), undefined=(), defined=(), data=(), kind="c_library"):
    unit = facts_data.Unit("a.c.o", frozenset(defined), frozenset(), frozenset(undefined), (), (), (), (),
                           data=tuple(data))
    return facts_data.Facts(P + name, kind, tuple(P + d for d in deps), (unit,))


def world(*modules):
    return {m.label: m for m in modules}


def doc(**modules):
    return {"module": {P + name: table for name, table in modules.items()}}


def decide(document, facts, **kw):
    return policy_check.decide(document, facts, third=THIRD, **kw)[0]


def errors(result):
    return sorted((f["rule"], f["module"].split(":")[1]) for f in result.findings if f["severity"] == "error")


class DecideTest(unittest.TestCase):
    def test_declared_at_or_above_the_floor_passes(self):
        facts = world(mod("rd", undefined=["read"]), mod("c"))
        result = decide(doc(rd={"profile": ["adapter", "pure"]}, c={"profile": "pure"}), facts)
        self.assertEqual(result.status, "PASS")
        floors = [f for f in result.findings if f["rule"] == "profile-floor"]
        self.assertEqual([(f["module"], f["floor"]) for f in floors], [(P + "c", ["pure"]), (P + "rd", ["adapter"])])

    def test_below_floor_names_rule_and_trigger(self):
        facts = world(mod("rd", undefined=["read", "pthread_create"]))
        result = decide(doc(rd={"profile": ["pure"]}), facts)
        got = sorted((f["profile"], f["floor_rule"], f["symbol"]) for f in result.findings
                     if f["rule"] == "profile-below-floor")
        self.assertEqual(got, [("adapter", "F-adapter", "read"), ("concurrent", "F-concurrent", "pthread_create")])

    def test_parser_finding_names_the_function(self):
        unit = structure_data.Unit("a.c", (), (structure_data.Func(
            "dec", "dec", "a.c", 1, 2, 1, False, False, 2, 0, 1, 1, (), (), (),
            type="int ( unsigned_char * , unsigned_long )"),), ())
        structures = {P + "p": structure_data.Structure(P + "p", "c_library", (), ("a.c",), (unit,))}
        result = decide(doc(p={"profile": ["adapter"]}), world(mod("p", defined=["dec"])), structures=structures)
        found = [f for f in result.findings if f["rule"] == "profile-below-floor"]
        self.assertEqual([(f["profile"], f["floor_rule"], f["function"]) for f in found], [("parser", "F-parser", "dec")])

    def test_unknown_missing_and_require(self):
        facts = world(mod("a"), mod("b"))
        result = decide(doc(a={"profile": ["nope"]}, b={}), facts)
        self.assertEqual(errors(result), [("profile-unknown", "a")])
        missing = [f for f in result.findings if f["rule"] == "profile-missing"]
        self.assertEqual([(f["module"], f["severity"]) for f in missing], [(P + "b", "info")])
        strict = decide(doc(a={"profile": ["pure"]}, b={}), facts, require=True)
        self.assertEqual(errors(strict), [("profile-missing", "b")])
        self.assertEqual(decide(doc(a={"profile": ["pure"]}, b={"profile": []}), facts, require=True).status, "FAIL")

    def test_missing_profile_is_not_below_floor_without_require(self):
        result = decide(doc(rd={}), world(mod("rd", undefined=["read"])))
        self.assertEqual(result.status, "PASS")

    def test_tests_and_unlisted_modules_are_not_judged(self):
        facts = world(mod("t", undefined=["read"], kind="c_test"), mod("x", undefined=["read"]))
        result = decide(doc(t={"profile": ["pure"]}), facts)
        self.assertEqual(result.findings, [])

    def test_level_floor_findings(self):
        facts = world(mod("top", deps=["base"], undefined=["b"]), mod("base", defined=["b"]))
        result = decide(doc(top={"level": "L3", "profile": "pure"}, base={"level": "L2", "profile": "pure"}), facts)
        f = [x for x in result.findings if x["rule"] == "level-below-floor"][0]
        self.assertEqual((f["module"], f["level"], f["floor"], f["dependent"]), (P + "base", "L2", "L3", P + "top"))
        ok = decide(doc(top={"level": "L3", "profile": "pure"}, base={"level": "L4", "profile": "pure"}), facts)
        self.assertEqual(ok.status, "PASS")

    def test_test_modules_do_not_raise_the_floor(self):
        facts = world(mod("t", deps=["base"], kind="c_test"), mod("base"))
        result = decide(doc(t={"level": "L5"}, base={"level": "L1", "profile": "pure"}), facts)
        self.assertEqual(errors(result), [])

    def test_architecture_exempts_data_edges(self):
        text = ('[layers]\norder = ["lo", "hi"]\n[layer."lo"]\nmodules = ["//p:base", "//p:shape"]\n'
                '[layer."hi"]\nmodules = ["//p:top", "//p:user"]\n'
                '[[edge]]\nfrom = "//p:top"\nto = "//p:base"\nkind = "pure"\n'
                '[[edge]]\nfrom = "//p:user"\nto = "//p:shape"\nkind = "data"\n')
        arch = layering.parse(text)
        facts = world(mod("top", deps=["base"]), mod("base"), mod("user", deps=["shape"]), mod("shape"))
        levels = {n: {"level": l, "profile": "pure"} for n, l in (("top", "L3"), ("base", "L1"), ("user", "L3"),
                                                                   ("shape", "L1"))}
        result = decide(doc(**levels), facts, arch=arch)
        self.assertEqual(errors(result), [("level-below-floor", "base")])
        self.assertIsNone(policy_check.edge_kind(None, P + "top", P + "base"))
        self.assertEqual(policy_check.edge_kind(arch, P + "user", P + "shape"), "data")
        self.assertEqual(policy_check.edge_kind(arch, P + "top", P + "shape"), None)

    def test_defective_policy_is_exit_2(self):
        facts = world(mod("a"))
        for bad in ({"profile": 3}, {"profile": ["pure", "pure"]}, {"profile": [1]}, {"level": "L9"}):
            with self.assertRaises(InternalError, msg=str(bad)):
                decide(doc(a=bad), facts)
        with self.assertRaises(InternalError):
            decide({"module": {"not-a-label": {}}}, facts)
        with self.assertRaises(InternalError):
            decide({"module": []}, facts)

    def test_emit_lines_sorted(self):
        lines = policy_check.emit_lines({P + "b": {"pure"}, P + "a": {"parser", "adapter"}})
        self.assertEqual(lines, ['[module."//p:a"]', 'profile = ["adapter", "parser"]',
                                 '[module."//p:b"]', 'profile = ["pure"]'])


class PolicyKeyTest(TempDirTestCase):
    def test_every_reader_accepts_profile(self):
        path = os.path.join(self.tmp, "policy.toml")
        with open(path, "w") as handle:
            handle.write('[global]\ndeny = ["kill"]\n[module."//p:a"]\nlevel = "L3"\nprofile = ["pure", "parser"]\n'
                         '[module."//p:b"]\nprofile = "adapter"\n')
        policy = facts_policy.load_policy(path)
        self.assertEqual(policy.modules["//p:a"].level, "L3")
        self.assertEqual(grade_policy.load_levels(path), {"//p:a": "L3"})
        self.assertEqual(grade_policy.load_document(path)["module"]["//p:b"]["profile"], "adapter")

    def test_without_the_key_nothing_changes(self):
        path = os.path.join(self.tmp, "policy.toml")
        with open(path, "w") as handle:
            handle.write('[global]\ndeny = []\n[module."//p:a"]\nlevel = "L2"\n')
        self.assertEqual(facts_policy.load_policy(path).modules["//p:a"].level, "L2")


class CliTest(TempDirTestCase):
    def write_facts(self, *modules):
        directory = os.path.join(self.tmp, "facts")
        os.makedirs(directory, exist_ok=True)
        for m in modules:
            unit = m.units[0]
            document = {"schema": 1, "label": m.label, "kind": m.kind, "deps": list(m.deps), "system_libs": [],
                        "units": [{"name": "a.c.o", "defined": sorted(unit.defined), "weak": [],
                                   "undefined": sorted(unit.undefined), "pragmas": [], "attributes": [],
                                   "identifiers": [], "line_directives": [], "mutable": [],
                                   "data": [{"name": n, "size": s, "section": sec, "local": loc}
                                            for n, s, sec, loc in unit.data]}]}
            with open(os.path.join(directory, m.label.split(":")[1] + ".json"), "w") as handle:
                json.dump(document, handle)
        return directory

    def policy(self, text):
        path = os.path.join(self.tmp, "policy.toml")
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def run_cli(self, *argv):
        out = os.path.join(self.tmp, "out.json")
        code = main(["policy-check", "--out", out, *argv])
        if not os.path.exists(out):
            return code, None
        with open(out) as handle:
            return code, json.load(handle)

    def test_exit_codes_and_out(self):
        facts = self.write_facts(mod("rd", undefined=["read"]))
        bad = self.policy('[module."//p:rd"]\nprofile = ["pure"]\n')
        code, result = self.run_cli("--policy", bad, "--facts", facts)
        self.assertEqual((code, result["status"]), (1, "FAIL"))
        good = self.policy('[module."//p:rd"]\nprofile = ["adapter"]\n')
        code, result = self.run_cli("--policy", good, "--facts", facts)
        self.assertEqual((code, result["status"]), (0, "PASS"))

    def test_fail_closed_on_bad_input(self):
        facts = self.write_facts(mod("rd"))
        self.assertEqual(self.run_cli("--policy", os.path.join(self.tmp, "missing.toml"), "--facts", facts)[0], 2)
        self.assertEqual(self.run_cli("--policy", self.policy("[module"), "--facts", facts)[0], 2)
        self.assertEqual(self.run_cli("--policy", self.policy(""), "--facts", os.path.join(self.tmp, "nodir"))[0], 2)
        self.assertEqual(self.run_cli("--policy", self.policy('[module."//p:rd"]\nprofile = 5\n'), "--facts", facts)[0], 2)
        self.assertEqual(self.run_cli("--policy", self.policy(""), "--facts", facts, "--structure",
                                      os.path.join(self.tmp, "nostruct"))[0], 2)
        self.assertEqual(self.run_cli("--policy", self.policy(""), "--facts", facts, "--architecture",
                                      os.path.join(self.tmp, "no.toml"))[0], 2)


if __name__ == "__main__":
    unittest.main()
