"""Gate `decoupling` inside `rigor grade` (wiring, the product files, the base of the change) and the baseline tool."""

import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

from rigor_lib import decoupling_baseline, grade_checks, grade_decoupling, grade_mutants, product_layout
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, Repo, TempDirTestCase, base_env
from tests.test_decoupling import CART, CONFIG, PAY, PAY_TEST, TEXT, facts, shop
from tests.test_decoupling_iface import CLOCK_H, HEADER

TOOL = GATE_DIR / "tools" / "decoupling.py"
PRODUCT = 'name = "p"\n[layout]\ninclude = ["lib/**", "shop/**"]\nexclude = []\n'
UNUSED = 'headers = ["pay.h"], deps = ["//lib/text:text"])'


def with_unused(tree):
    tree["shop/parts/pay/BUCK"] = tree["shop/parts/pay/BUCK"].replace('headers = ["pay.h"])', UNUSED)
    return tree


class Graded(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.repo = Repo(self.tmp / "src")
        self.products = self.sub("products")
        self.directory = self.sub("products/p")
        (self.directory / "product.toml").write_text(PRODUCT)

    def commit(self, tree):
        for path in self.repo.git("ls-files").split():
            self.repo.remove(path)
        for path, text in tree.items():
            self.repo.write(path, text)
        return self.repo.commit()

    def grading(self, base_tree, head_tree=None, config=CONFIG, baseline=None, status=None):
        base = self.commit(base_tree)
        head = self.commit(head_tree) if head_tree is not None else base
        if config is not None:
            (self.directory / "decoupling.toml").write_text(config)
        if baseline is not None:
            (self.directory / "decoupling-baseline.toml").write_text(baseline)
        paths = self.repo.git("ls-files").split()
        return SimpleNamespace(
            args=SimpleNamespace(product=str(self.directory / "product.toml")), src=str(self.repo.root), base=base,
            head=head, tree=str(self.repo.root), product_paths=paths, facts=None,
            product=product_layout.load_product(str(self.directory / "product.toml")),
            status=dict({"toolchain": "PASS", "assemble": "PASS", "buckfiles": "PASS"}, **(status or {})))

    def run_gate(self, g, world=None):
        built = grade_checks.FactsBuild("facts", "libc", {"facts_targets": 1})
        with mock.patch.object(grade_checks, "build_facts", return_value=built), \
                mock.patch.object(grade_decoupling.facts_data, "load_facts_dir",
                                  side_effect=lambda _d: world or self.world(g)):
            return grade_decoupling.decoupling_gate(g)

    @staticmethod
    def world(g):
        return {label: facts(label) for label in grade_decoupling.head_model(g).targets}

    @staticmethod
    def errors(result):
        return sorted((f["rule"], f.get("entry") or f.get("reason")) for f in result.findings if f["severity"] == "error")


class Gate(Graded):
    def test_a_product_without_the_file_passes_with_not_applicable_and_reads_nothing(self):
        g = self.grading(shop(), config=None, status={"toolchain": "NOT_RUN", "assemble": "FAIL", "buckfiles": "FAIL"})
        (self.directory / "decoupling-baseline.toml").write_text("not toml [")
        result = grade_decoupling.decoupling_gate(g)
        self.assertEqual((result.gate, result.status, result.metadata), ("decoupling", "PASS", {}))
        self.assertEqual(result.findings, [{"rule": "not-applicable", "severity": "info"}])

    def test_it_needs_the_toolchain_the_tree_the_build_files_and_the_facts(self):
        for gate in ("toolchain", "assemble", "buckfiles"):
            self.assertIsNone(self.run_gate(self.grading(shop(), status={gate: "FAIL"})), gate)
        g = self.grading(shop())
        with mock.patch.object(grade_checks, "build_facts", return_value="build failed"):
            self.assertIsNone(grade_decoupling.decoupling_gate(g))

    def test_broken_product_files_are_internal_errors(self):
        with self.assertRaises(InternalError):
            self.run_gate(self.grading(shop(), config="nonsense = 1\n", status={"toolchain": "FAIL"}))
        with self.assertRaises(InternalError):
            self.run_gate(self.grading(shop(), baseline="other-rule = []\n"))

    def test_a_clean_tree_passes_and_reports_its_inputs_and_counts(self):
        result = self.run_gate(self.grading(shop()))
        self.assertEqual(result.status, "PASS")
        inputs = [f for f in result.findings if f["rule"] == "decoupling-inputs"]
        self.assertEqual(len(inputs[0]["config_sha256"]), 64)
        self.assertIsNone(inputs[0]["baseline_sha256"])
        self.assertEqual(result.metadata["tests"], {"unit": 3, "integration": 1, "simulation": 0, "unleveled": 0})
        self.assertEqual(result.metadata["rules"]["unused-dep"], {"violations": 0, "new": 0, "stale": 0})
        self.assertEqual(result.metadata["fan_out"]["per_module"][TEXT], [2, 3])
        self.assertEqual(result.metadata["facts_targets"], 1)

    def test_a_new_violation_fails(self):
        result = self.run_gate(self.grading(shop(), with_unused(shop())))
        self.assertEqual(self.errors(result), [("unused-dep", PAY + " -> " + TEXT)])
        found = [f for f in result.findings if f["rule"] == "unused-dep"][0]
        self.assertEqual((found["target"], found["dep"], found["list"]), (PAY, TEXT, "deps"))

    def test_a_baselined_violation_passes_and_a_fixed_one_is_stale(self):
        text = decoupling_baseline.render({"unused-dep": [PAY + " -> " + TEXT]})
        self.assertEqual(self.run_gate(self.grading(with_unused(shop()), baseline=text)).status, "PASS")
        result = self.run_gate(self.grading(with_unused(shop()), shop(), baseline=text))
        self.assertEqual(self.errors(result), [("stale-baseline", PAY + " -> " + TEXT)])

    def test_the_facts_decide_what_the_objects_use(self):
        g = self.grading(with_unused(shop()))
        world = self.world(g)
        world.update({PAY: facts(PAY, ["pay_take"], ["text_len"], [TEXT]), TEXT: facts(TEXT, ["text_len"])})
        self.assertEqual(self.run_gate(g, world).status, "PASS")

    def test_a_frozen_header_is_compared_with_the_merge_base(self):
        base = shop()
        base[CLOCK_H] = HEADER
        head = dict(base)
        head[CLOCK_H] = HEADER.replace("    void *self;", "    int flags;\n    void *self;")
        result = self.run_gate(self.grading(base, head))
        self.assertEqual(self.errors(result), [("interface-changed", "declaration")])
        self.assertEqual(result.metadata["frozen"], ["//shop/contracts/clock:clock"])
        found = [f for f in result.findings if f["rule"] == "interface-changed"][0]
        self.assertEqual((found["module"], found["file"], found["line"]), ("//shop/contracts/clock:clock", CLOCK_H, 4))

    def test_without_a_contract_or_frozen_list_the_base_is_not_read(self):
        g = self.grading(shop(), config=CONFIG.replace('contract = ["//shop/contracts/**"]\n', ""))
        g.base = "0" * 40   # would be an internal error if it were resolved
        self.assertEqual(self.run_gate(g).status, "PASS")

    def test_files_the_layout_leaves_out_are_not_in_the_base_model(self):
        tree = shop()
        tree["docs/BUCK"] = "not a build file ("
        g = self.grading(tree)
        model = grade_decoupling.commit_model(g.src, g.head, g.product)
        self.assertNotIn("docs/BUCK", model.paths)
        self.assertIn(CART, model.targets)


class TestLevels(Graded):
    def test_declared_test_packages_are_no_modules_own_tests(self):
        g = self.grading(shop())
        tests = {"//shop/itest/flow:flow_test", PAY_TEST}
        self.assertEqual(grade_decoupling.apart_tests(g, tests), frozenset(["//shop/itest/flow:flow_test"]))
        (self.directory / "decoupling.toml").unlink()
        self.assertEqual(grade_decoupling.apart_tests(g, tests), frozenset())

    def test_own_tests_leave_them_out_even_when_a_library_hides_in_the_package(self):
        lib, test = "//shop/itest/flow:helper", "//shop/itest/flow:flow_test"
        layout = grade_mutants.Layout(frozenset([lib]), frozenset(), frozenset([test]), {lib: (), test: (lib,)})
        self.assertEqual(grade_mutants.own_tests(layout, lib), (test,))
        apart = grade_mutants.Layout(layout.libs, layout.binaries, layout.tests, layout.deps, apart=frozenset([test]))
        self.assertEqual(grade_mutants.own_tests(apart, lib), ())
        self.assertEqual(grade_mutants.direct_tests(apart, lib), (test,))


class Tool(Graded):
    def tool(self, *args):
        done = subprocess.run([sys.executable, "-I", "-B", str(TOOL), "baseline", "--product-repo", str(self.repo.root),
                               "--product", "p", "--products-dir", str(self.products)] + list(args),
                              env=base_env(), capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout, done.stderr

    def test_it_prints_the_baseline_of_a_commit_twice_the_same(self):
        g = self.grading(with_unused(shop()))
        (self.directory / "policy.toml").write_text('[global]\ndeny = []\ntrusted = []\n')
        code, out, err = self.tool("--commit", g.head)
        self.assertEqual((code, out), (0, decoupling_baseline.render({"unused-dep": [PAY + " -> " + TEXT]})), err)
        self.assertEqual(self.tool("--commit", "main")[1], out)
        self.assertIn("unused-dep", err)

    def test_check_compares_with_the_committed_file(self):
        g = self.grading(with_unused(shop()), baseline=decoupling_baseline.render({"unused-dep": [PAY + " -> " + TEXT]}))
        (self.directory / "policy.toml").write_text('[global]\ndeny = []\ntrusted = []\n')
        self.assertEqual(self.tool("--commit", g.head, "--check")[:2], (0, ""))
        (self.directory / "decoupling-baseline.toml").write_text('unused-dep = ["//gone:gone -> //lib/text:text"]\n')
        code, out, err = self.tool("--commit", g.head, "--check")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("+ unused-dep: %s -> %s" % (PAY, TEXT), err)
        self.assertIn("- unused-dep: //gone:gone -> //lib/text:text", err)

    def test_unreadable_inputs_are_exit_2(self):
        g = self.grading(shop())
        (self.directory / "policy.toml").write_text('[global]\ndeny = []\ntrusted = []\n')
        self.assertEqual(self.tool("--commit", "no-such-commit")[0], 2)
        self.assertEqual(self.tool("--commit", g.head, "--facts", str(self.tmp / "none"))[0], 2)
        (self.directory / "decoupling.toml").unlink()
        self.assertEqual(self.tool("--commit", g.head)[0], 2)
