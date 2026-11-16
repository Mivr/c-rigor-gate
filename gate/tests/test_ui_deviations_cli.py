"""U13: the `rigor ui-deviations` command end to end (exit codes, exact output, layout, symlinks, bad inputs)."""

import json
import os
import tomllib

from rigor_lib import product_layout
from rigor_lib import ui_deviations as ud
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase, run_rigor
from tests.test_ui_deviations import tag
from tests.test_ui_deviations_ratchet import DATA, HEADERS, PRODUCT_DIR, accepted_for, comment


class Command(TempDirTestCase):
    GOOD_BASE = ('schema = "ui-deviations/3"\nproduct = "p"\ncap = 1\nreference_bug_link_prefix = "https://x/i/"\n'
                 '[accepted."UI-A1"]\nuntil = "T200"\nsha256 = "%s"\n')
    SECTIONS = 'schema = "ui-deviation-sections/2"\nproduct = "p"\n[headers]\n'

    @staticmethod
    def listed(**counts):
        return "".join('[headers."%s"]\ncount = %d\nlabels = [%s]\n' % (k.replace("_", "/") + ".h", v,
                       ", ".join('"e%d"' % i for i in range(v))) for k, v in counts.items())

    def product(self, headers, baseline=None, include='["a/**"]', sections=None):
        root = self.sub("tree")
        for rel, text in headers.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text if isinstance(text, bytes) else text.encode())
        home = self.sub("products/p")
        (home / "ui").mkdir(exist_ok=True)
        (home / "product.toml").write_text('name = "p"\n[layout]\ninclude = %s\n' % include)
        pin = accepted_for("a/x.h", tag("UI-A1"))["UI-A1"][1]
        (home / "ui" / "deviations.toml").write_text(baseline or self.GOOD_BASE % pin)
        (home / "ui" / "deviation-sections.toml").write_text(self.SECTIONS if sections is None else sections)
        return root, home / "product.toml"

    def run_cli(self, root, product, today="2026-11-15", *extra):
        return run_rigor(["ui-deviations", "--root", root, "--product", product, "--today", today, *extra])

    def test_a_clean_tree_passes_with_the_house_output(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1"))})
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout, out.stderr), (0, "ui-deviations: PASS (0 findings)\n", ""))

    def test_findings_exit_1_with_exact_sorted_lines_and_a_result_file(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1", until="2020-01-01"), tag("UI-B2")),
                                      "a/y.h": "/* Deviations:\n 1. a\n 2. b */\n"})
        result = self.tmp / "r.json"
        out = self.run_cli(root, product, "2026-11-15", "--out", result)
        lines = [
            '{"acknowledged":0,"detected":2,"entries":2,"line":1,"path":"a/y.h","rule":"deviation-untagged","severity":"error","tags":0}',
            '{"cap":1,"count":2,"rule":"deviation-over-cap","severity":"error"}',
            '{"id":"UI-A1","line":2,"path":"a/x.h","rule":"deviation-changed","severity":"error"}',
            '{"id":"UI-A1","line":2,"path":"a/x.h","rule":"deviation-expired","severity":"error","until":"2020-01-01"}',
            '{"id":"UI-B2","line":3,"path":"a/x.h","rule":"deviation-new","severity":"error"}']
        self.assertEqual(out.stdout, "ui-deviations: FAIL (5 findings)\n" + "".join("  %s\n" % l for l in lines))
        self.assertEqual(out.code, 1)
        doc = json.loads(result.read_text())
        self.assertEqual((doc["gate"], doc["status"], doc["metadata"]),
                         ("ui-deviations", "FAIL", {"files": 2, "product": "p", "tags": 2, "today": "2026-11-15"}))

    def test_the_output_is_byte_identical_and_independent_of_creation_order(self):
        names = ["a/%s.h" % n for n in "dcba"]
        texts = {n: comment(tag("UI-%s1" % n[2].upper())) for n in names}
        outs = []
        for order in (names, list(reversed(names))):
            self.setUp()
            root, product = self.product({n: texts[n] for n in order})
            outs.append(self.run_cli(root, product).stdout)
            outs.append(self.run_cli(root, product).stdout)
        self.assertEqual(len(set(outs)), 1)
        self.assertIn("deviation-over-cap", outs[0])

    def test_only_files_the_layout_copies_are_read_and_the_walk_follows_the_layout(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1")), "b/y.h": comment(tag("UI-Z9")),
                                      "a/z.txt": comment(tag("UI-Z8")), "third_party/q.h": comment(tag("UI-Z7")),
                                      "gate/q.h": comment(tag("UI-Z6")), "a/.git/q.h": comment(tag("UI-Z5")),
                                      "Third_Party/q.h": comment(tag("UI-Z4")), "a/X.H": "/* Deviations: */"},
                                     include='["a/**", "third_party/**", "gate/**", "Third_Party/**"]')
        out = self.run_cli(root, product)
        self.assertEqual(out.code, 1)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (3 findings)\n"
            '  {"cap":1,"count":2,"rule":"deviation-over-cap","severity":"error"}\n'
            '  {"id":"UI-Z4","line":2,"path":"Third_Party/q.h","rule":"deviation-new","severity":"error"}\n'
            '  {"line":1,"path":"a/X.H","rule":"deviation-unlabelled","severity":"error"}\n')

    def test_a_symlinked_file_or_directory_that_would_be_graded_is_a_finding(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1")), "outside.h": comment(tag("UI-Z9")), "other/q.h": "int q;\n"})
        os.symlink(str(root / "outside.h"), str(root / "a" / "link.h"))
        os.symlink(str(root / "other"), str(root / "a" / "dir"))
        os.symlink(str(root / "other"), str(root / "b_dir"))          # not copied by the layout: not reported
        out = self.run_cli(root, product)
        self.assertEqual(out.code, 1)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (2 findings)\n"
                         '  {"line":0,"path":"a/dir","rule":"deviation-malformed","severity":"error","why":"symlink"}\n'
                         '  {"line":0,"path":"a/link.h","rule":"deviation-malformed","severity":"error","why":"symlink"}\n')

    def test_a_section_in_a_source_file_is_misplaced(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1")), "a/y.c": "/* Deviations:\n 1. a */\n"})
        out = self.run_cli(root, product)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (1 findings)\n"
                         '  {"line":1,"path":"a/y.c","rule":"deviation-misplaced","severity":"error","what":"section"}\n')

    def test_a_listed_header_that_is_missing_fails_even_without_any_prose(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1"))}, sections=self.SECTIONS + self.listed(a_gone=3))
        out = self.run_cli(root, product)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (1 findings)\n"
                         '  {"acknowledged":3,"header":"absent","path":"a/gone.h","rule":"deviation-section-missing","severity":"error","tags":0}\n')

    def test_bad_inputs_are_exit_2_with_one_line_and_no_traceback(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        cases = {
            "bad date": (root, product, "2026-02-30"), "date format": (root, product, "15/11/2026"),
            "no root": (self.tmp / "nope", product, "2026-11-15"), "no product": (root, self.tmp / "nope.toml", "2026-11-15"),
        }
        for name, (r, p, today) in cases.items():
            with self.subTest(name=name):
                out = self.run_cli(r, p, today)
                self.assertEqual((out.code, out.stdout), (2, ""))
                self.assertTrue(out.stderr.startswith("rigor: internal error: "), out.stderr)
                self.assertNotIn("Traceback", out.stderr)

    def test_a_repeated_option_is_an_error(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        for extra in (("--today", "2026-11-16"), ("--root", root), ("--product", product)):
            with self.subTest(extra=extra[0]):
                out = self.run_cli(root, product, "2026-11-15", *extra)
                self.assertEqual((out.code, out.stdout), (2, ""))
                self.assertIn("exactly once", out.stderr)
                self.assertNotIn("Traceback", out.stderr)

    def test_a_missing_or_broken_input_file_is_exit_2(self):
        for name in ("deviations.toml", "deviation-sections.toml"):
            with self.subTest(name=name):
                self.setUp()
                root, product = self.product({"a/x.h": "int a;\n"})
                (product.parent / "ui" / name).unlink()
                out = self.run_cli(root, product)
                self.assertEqual((out.code, out.stdout), (2, ""))
                self.assertNotIn("Traceback", out.stderr)
                (product.parent / "ui" / name).write_text("x = = 1")
                out = self.run_cli(root, product)
                self.assertEqual((out.code, out.stdout), (2, ""))
                self.assertIn(name, out.stderr)
                self.assertNotIn("Traceback", out.stderr)

    def test_a_non_utf8_header_is_a_finding_not_a_crash(self):
        root, product = self.product({"a/x.h": b"/* \xff */"})
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (1, "ui-deviations: FAIL (2 findings)\n"
            '  {"id":"UI-A1","rule":"deviation-removed","severity":"info"}\n'
            '  {"line":1,"path":"a/x.h","rule":"deviation-malformed","severity":"error","why":"not-utf-8"}\n'))

    def test_the_committed_product_files_read_a_tree_that_really_holds_a_header(self):
        """Not vacuous: one header is read (metadata), and the only findings are the 20 + 3 listed headers' ones from the
        committed deviation-sections.toml, which this tree does not contain."""
        root = self.sub("tree")
        (root / "apps" / "lockers" / "lk" / "audit").mkdir(parents=True)
        (root / "apps" / "lockers" / "lk" / "audit" / "x.h").write_text("/* ordinary */\nint a;\n")
        result = self.tmp / "r.json"
        out = run_rigor(["ui-deviations", "--root", root, "--product", PRODUCT_DIR / "product.toml", "--today", "2026-11-15",
                         "--out", result])
        doc = json.loads(result.read_text())
        listed = tomllib.loads((PRODUCT_DIR / "ui" / "deviation-sections.toml").read_text())["headers"]
        self.assertEqual(out.code, 1)
        self.assertEqual(doc["metadata"], {"files": 1, "product": "business-apps", "tags": 0, "today": "2026-11-15"})
        self.assertEqual(sorted((f["rule"], f["path"]) for f in doc["findings"]), [("deviation-section-missing", p) for p in sorted(listed)])

    def test_the_real_header_copies_through_the_cli(self):
        root = self.sub("tree")
        (root / "a").mkdir()
        for name, _, _ in HEADERS:
            (root / "a" / name).write_bytes((DATA / name).read_bytes())
        root2, product = self.product({}, sections=self.SECTIONS + "".join('[headers."a/%s"]\ncount = %d\nlabels = [%s]\n' % (n, e, ", ".join('"e%d"' % i for i in range(e)))
                                             for n, _, e in sorted(HEADERS)))
        out = self.run_cli(root, product)
        self.assertEqual(out.code, 1)
        self.assertEqual([json.loads(l)["rule"] for l in out.stdout.splitlines()[1:]] , ["deviation-untagged"] * 4 + ["deviation-removed"])

    def test_the_command_without_arguments_prints_one_line_and_exits_2(self):
        out = run_rigor(["ui-deviations"])
        self.assertEqual((out.code, out.stdout), (2, ""))
        self.assertEqual(out.stderr, "rigor: internal error: InternalError: --root must be given exactly once\n")

    def test_a_fifo_with_a_header_name_is_a_finding_and_is_never_opened(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1"))})
        os.mkfifo(str(root / "a" / "pipe.h"))
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (1, "ui-deviations: FAIL (1 findings)\n"
                         '  {"line":0,"path":"a/pipe.h","rule":"deviation-malformed","severity":"error","why":"not-a-regular-file"}\n'))

    def test_a_product_toml_with_a_toml_error_is_exit_2_naming_the_file(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        product.write_text("name = = 1\n")
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (2, ""))
        self.assertIn("product.toml", out.stderr)
        self.assertNotIn("Traceback", out.stderr)
        product.write_bytes(b"\xff\xfe")
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (2, ""))
        self.assertNotIn("Traceback", out.stderr)

    def test_a_root_that_is_a_file_is_exit_2(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        out = self.run_cli(root / "a" / "x.h", product)
        self.assertEqual((out.code, out.stdout), (2, ""))
        self.assertIn("not a directory", out.stderr)

    def test_an_unreadable_directory_is_the_house_error_never_a_silent_skip(self):
        root, _ = self.product({"a/x.h": "int a;\n", "a/locked/y.h": "int b;\n"})
        config = _config(self.tmp)
        real = os.scandir

        def scandir(path):
            if str(path).endswith("locked"):
                raise PermissionError(13, "Permission denied", str(path))
            return real(path)

        os.scandir = scandir
        try:
            with self.assertRaises(InternalError) as caught:
                ud.discover(str(root), config)
        finally:
            os.scandir = real
        self.assertIn("locked", str(caught.exception))
        self.assertIn("Permission denied", str(caught.exception))
        with self.assertRaises(InternalError):
            ud.discover(str(root / "nowhere"), config)

    def test_a_listed_header_that_exists_in_another_case_names_the_real_file(self):
        root, product = self.product({"a/X.H": comment(tag("UI-A1"))}, sections=self.SECTIONS + self.listed(a_x=1))
        out = self.run_cli(root, product)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (2 findings)\n"
            '  {"acknowledged":1,"actual":"a/X.H","header":"absent","path":"a/x.h","rule":"deviation-section-missing","severity":"error","tags":0}\n'
            '  {"id":"UI-A1","line":2,"path":"a/X.H","rule":"deviation-changed","severity":"error"}\n')


def _config(tmp):
    path = tmp / "pc.toml"
    path.write_text('name = "p"\n[layout]\ninclude = ["a/**"]\n')
    return product_layout.load_product(str(path))


if __name__ == "__main__":
    unittest.main()
