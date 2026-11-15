"""U13: the ratchet of `rigor_lib.ui_deviations` (new / over-cap / removed / expired / duplicate), the baseline loader, the
judge hook, the real headers (copies under data/ui_deviations/) and the `rigor ui-deviations` command."""

import datetime
import hashlib
import json
import os
import random
import unittest
from pathlib import Path

from rigor_lib import ui_deviations as ud
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase, run_rigor
from tests.test_ui_deviations import BASE, LINK, TODAY, tag

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "ui_deviations"
REAL = HERE.parent.parent / "products" / "business-apps" / "ui" / "deviations.toml"
# The three real headers and the entry count each section must give (counted by hand from the files).
HEADERS = (("screens.h", 12), ("selftest.h", 3), ("preflight.h", 1))


def base(cap=10, accepted=()):
    return ud.Baseline("business-apps", cap, tuple(accepted), LINK)


def comment(*tags):
    return "/*\n" + "".join(" * %s\n" % t for t in tags) + " */\n"


def run(files, baseline=BASE, today=TODAY):
    return ud.analyse([(p, t.encode()) for p, t in files], baseline, today)


def rules(found):
    return sorted((f["rule"], f.get("id", f.get("path", ""))) for f in found)


class Ratchet(unittest.TestCase):
    def test_no_tags_and_an_empty_baseline_is_clean(self):
        self.assertEqual(run([("a.h", "int x;\n")], base(0)), ((), ()))

    def test_a_tag_outside_the_baseline_is_new(self):
        tags, found = run([("a.h", "\n" + comment(tag("UI-A1")))], base(1))
        self.assertEqual([t.id for t in tags], ["UI-A1"])
        self.assertEqual(found, ({"rule": "deviation-new", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A1"},))

    def test_an_accepted_tag_is_clean_and_one_above_the_cap_is_over(self):
        text = comment(tag("UI-A1"), tag("UI-A2"))
        self.assertEqual(run([("a.h", text)], base(2, ["UI-A1", "UI-A2"]))[1], ())
        _, found = run([("a.h", text)], base(1, ["UI-A1"]))
        self.assertEqual(found, ({"rule": "deviation-new", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A2"},
                                 {"rule": "deviation-over-cap", "severity": "error", "count": 2, "cap": 1}))

    def test_a_cap_of_zero_makes_every_tag_new_and_over_cap(self):
        _, found = run([("a.h", comment(tag("UI-A1")))], base(0))
        self.assertEqual(rules(found), [("deviation-new", "UI-A1"), ("deviation-over-cap", "")])

    def test_an_accepted_id_without_a_tag_is_removed_info(self):
        _, found = run([("a.h", comment(tag("UI-A1")))], base(3, ["UI-A1", "UI-B2"]))
        self.assertEqual(found, ({"rule": "deviation-removed", "severity": "info", "id": "UI-B2"},))
        status = ud.GateResult("g", list(found), {}).status
        self.assertEqual(status, "PASS")

    def test_duplicate_ids_in_one_file_and_across_files(self):
        _, found = run([("b.h", comment(tag("UI-A1"))), ("a.h", comment(tag("UI-A1"), tag("UI-A1")))], base(1, ["UI-A1"]))
        self.assertEqual(found, (
            {"rule": "deviation-malformed", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A1",
             "why": "duplicate-id", "first": "a.h:2"},
            {"rule": "deviation-malformed", "severity": "error", "path": "b.h", "line": 2, "id": "UI-A1",
             "why": "duplicate-id", "first": "a.h:2"}))

    def test_expired_against_the_passed_date_only(self):
        for until, expired in (("2026-11-14", True), ("2026-11-15", False), ("2026-11-16", False), ("T104", False),
                               ("2020-01-01", True)):
            with self.subTest(until=until):
                _, found = run([("a.h", comment(tag("UI-A1", until=until)))], base(1, ["UI-A1"]))
                self.assertEqual(found, ({"rule": "deviation-expired", "severity": "error", "path": "a.h", "line": 2,
                                          "id": "UI-A1", "until": until},) if expired else ())

    def test_the_same_files_judge_differently_on_another_date(self):
        files = [("a.h", comment(tag("UI-A1", until="2026-12-01")))]
        self.assertEqual(run(files, base(1, ["UI-A1"]), datetime.date(2026, 12, 1))[1], ())
        self.assertEqual(len(run(files, base(1, ["UI-A1"]), datetime.date(2026, 12, 2))[1]), 1)

    def test_a_malformed_tag_is_a_finding_and_is_not_counted_as_a_tag(self):
        tags, found = run([("a.h", comment(tag("UI-A1", reason="x")))], base(0))
        self.assertEqual((tags, [f["rule"] for f in found]), ((), ["deviation-malformed"]))

    def test_the_hook_marks_pinned_and_stale(self):
        tags, _ = run([("a.h", comment(tag("UI-A1"), tag("UI-B2"), tag("UI-C3")))])
        found = ud.judge_tags(tags, frozenset({"UI-A1", "UI-C3", "UI-NOTAG-1"}))
        self.assertEqual(found, (
            {"rule": "pinned-deviation", "severity": "info", "path": "a.h", "line": 2, "id": "UI-A1"},
            {"rule": "deviation-stale", "severity": "error", "path": "a.h", "line": 3, "id": "UI-B2"},
            {"rule": "pinned-deviation", "severity": "info", "path": "a.h", "line": 4, "id": "UI-C3"}))
        self.assertEqual(ud.judge_tags((), set()), ())

    def test_the_hook_refuses_a_wrong_argument(self):
        tags, _ = run([("a.h", comment(tag("UI-A1")))])
        for tags_arg, div in ((tags, ["UI-A1"]), (tags, {1}), (tags, None), (tags, "UI-A1"), (({"id": "UI-A1"},), set())):
            with self.subTest(div=div):
                with self.assertRaises(InternalError):
                    ud.judge_tags(tags_arg, div)


class Deterministic(unittest.TestCase):
    def test_the_result_does_not_depend_on_the_order_of_the_files(self):
        files = [("d/%d.h" % i, comment(tag("UI-A%d" % (i % 4)), tag("UI-B%d" % i, until="2020-01-01"))
                  + "/* DISAGREEMENTS\n 1. a\n 2. b\n 3. c */\n") for i in range(8)]
        files.append(("e.h", "/* @deviation(oops */"))
        first = run(files, base(3, ["UI-Q1"]))
        for seed in range(6):
            shuffled = list(files)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(run(shuffled, base(3, ["UI-Q1"])), first)
        result = ud.GateResult(ud.GATE_ID, list(first[1]), {})
        self.assertEqual(result.to_json_bytes(), ud.GateResult(ud.GATE_ID, list(reversed(first[1])), {}).to_json_bytes())


class Loader(TempDirTestCase):
    GOOD = ('schema = "ui-deviations/1"\nproduct = "business-apps"\ncap = 2\naccepted = ["UI-A1", "UI-B2"]\n'
            "reference_bug_link_pattern = 'https://x/[0-9]+'\n")

    def load(self, text, product="business-apps"):
        path = self.tmp / "deviations.toml"
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return ud.load_baseline(str(path), product)

    def test_the_good_file_loads_immutably(self):
        loaded = self.load(self.GOOD)
        self.assertEqual(loaded, ud.Baseline("business-apps", 2, ("UI-A1", "UI-B2"), "https://x/[0-9]+"))

    def test_every_defect_is_exit_2(self):
        good = self.GOOD
        bad = {
            "unknown key": good + "extra = 1\n",
            "missing key": good.replace("cap = 2\n", ""),
            "wrong schema": good.replace("ui-deviations/1", "ui-deviations/2"),
            "other product": good.replace('"business-apps"', '"annas-c"'),
            "cap string": good.replace("cap = 2", 'cap = "2"'),
            "cap bool": good.replace("cap = 2", "cap = true").replace('["UI-A1", "UI-B2"]', "[]"),
            "cap negative": good.replace("cap = 2", "cap = -1").replace('["UI-A1", "UI-B2"]', "[]"),
            "cap float": good.replace("cap = 2", "cap = 2.0"),
            "accepted not a list": good.replace('["UI-A1", "UI-B2"]', '"UI-A1"'),
            "accepted element type": good.replace('"UI-B2"', "2"),
            "accepted bad id": good.replace('"UI-B2"', '"ui-b2"'),
            "accepted unsorted": good.replace('["UI-A1", "UI-B2"]', '["UI-B2", "UI-A1"]'),
            "accepted duplicate": good.replace('"UI-B2"', '"UI-A1"'),
            "above the cap": good.replace("cap = 2", "cap = 1"),
            "empty pattern": good.replace("'https://x/[0-9]+'", '""'),
            "pattern not a string": good.replace("'https://x/[0-9]+'", "1"),
            "pattern not a regex": good.replace("'https://x/[0-9]+'", "'(['"),
            "not toml": "cap = = 2\n",
            "duplicate key": good + "cap = 3\n",
            "not utf-8": b"\xff\xfe",
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(InternalError):
                    self.load(text)

    def test_a_missing_file_is_an_error(self):
        with self.assertRaises(OSError):
            ud.load_baseline(str(self.tmp / "none.toml"), "business-apps")

    def test_the_committed_business_apps_baseline_is_empty_with_cap_zero(self):
        self.assertEqual(ud.load_baseline(str(REAL), "business-apps"), ud.Baseline("business-apps", 0, (), LINK))


class RealHeaders(unittest.TestCase):
    def read(self, name):
        return (DATA / name).read_bytes()

    def test_the_copies_are_the_recorded_bytes(self):
        for name, _ in HEADERS:
            with self.subTest(name=name):
                recorded = (DATA / (name + ".sha256")).read_text(encoding="ascii").strip()
                self.assertEqual(len(recorded), 64)
                self.assertEqual(hashlib.sha256(self.read(name)).hexdigest(), recorded)

    def test_each_real_header_has_its_exact_entry_count_and_no_tag(self):
        for name, entries in HEADERS:
            with self.subTest(name=name):
                tags, bad, secs = ud.scan_header(name, self.read(name), LINK)
                self.assertEqual((tags, bad, [count for _, count in secs]), ((), (), [entries]))
                _, found = ud.analyse([(name, self.read(name))], BASE, TODAY)
                self.assertEqual(found, ({"rule": "deviation-untagged", "severity": "error", "path": name,
                                          "line": secs[0][0], "entries": entries, "tags": 0},))

    def test_the_heading_lines_of_the_copies(self):
        got = {name: ud.scan_header(name, self.read(name), LINK)[2][0][0] for name, _ in HEADERS}
        self.assertEqual(got, {"screens.h": 180, "selftest.h": 75, "preflight.h": 139})

    def test_one_tag_per_entry_clears_the_finding_and_one_fewer_does_not(self):
        for name, entries in HEADERS:
            ids = ["UI-%s%d" % (name[0].upper(), k) for k in range(entries)]
            full = self.read(name).decode() + comment(*[tag(i) for i in ids])
            short = self.read(name).decode() + comment(*[tag(i) for i in ids[:-1]])
            with self.subTest(name=name):
                _, found = run([(name, full)], base(entries, sorted(ids)))
                self.assertEqual(found, ())
                _, found = run([(name, short)], base(entries, sorted(ids[:-1])))
                self.assertEqual([(f["rule"], f["entries"], f["tags"]) for f in found],
                                 [("deviation-untagged", entries, entries - 1)])

    def test_a_malformed_tag_does_not_count_towards_the_entries(self):
        name = "selftest.h"
        text = self.read(name).decode() + comment(tag("UI-S1"), tag("UI-S2"), tag("UI-S3", reason="bogus"))
        _, found = run([(name, text)], base(3, ["UI-S1", "UI-S2"]))
        self.assertEqual(sorted((f["rule"], f.get("tags")) for f in found),
                         [("deviation-malformed", None), ("deviation-untagged", 2)])


class Command(TempDirTestCase):
    def product(self, headers, baseline=None, include='["a/**"]'):
        root = self.sub("tree")
        for rel, text in headers.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text if isinstance(text, bytes) else text.encode())
        home = self.sub("products/p")
        (home / "ui").mkdir(exist_ok=True)
        (home / "product.toml").write_text('name = "p"\n[layout]\ninclude = %s\n' % include)
        (home / "ui" / "deviations.toml").write_text(baseline or (
            'schema = "ui-deviations/1"\nproduct = "p"\ncap = 1\naccepted = ["UI-A1"]\n'
            "reference_bug_link_pattern = 'https://x/[0-9]+'\n"))
        return root, home / "product.toml"

    def run_cli(self, root, product, today="2026-11-15", *extra):
        return run_rigor(["ui-deviations", "--root", root, "--product", product, "--today", today, *extra])

    def test_a_clean_tree_passes_with_the_house_output(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1"))})
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout, out.stderr), (0, "ui-deviations: PASS (0 findings)\n", ""))

    def test_findings_exit_1_with_exact_sorted_lines_and_a_result_file(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1", until="2020-01-01"), tag("UI-B2")),
                                      "a/y.h": "/* DISAGREEMENTS\n 1. a\n 2. b */\n"})
        result = self.tmp / "r.json"
        out = self.run_cli(root, product, "2026-11-15", "--out", result)
        lines = [
            '{"cap":1,"count":2,"rule":"deviation-over-cap","severity":"error"}',
            '{"entries":2,"line":1,"path":"a/y.h","rule":"deviation-untagged","severity":"error","tags":0}',
            '{"id":"UI-A1","line":2,"path":"a/x.h","rule":"deviation-expired","severity":"error","until":"2020-01-01"}',
            '{"id":"UI-B2","line":3,"path":"a/x.h","rule":"deviation-new","severity":"error"}']
        self.assertEqual(out.stdout, "ui-deviations: FAIL (4 findings)\n" + "".join("  %s\n" % l for l in lines))
        self.assertEqual(out.code, 1)
        doc = json.loads(result.read_text())
        self.assertEqual((doc["gate"], doc["status"], doc["metadata"]),
                         ("ui-deviations", "FAIL", {"headers": 2, "product": "p", "tags": 2, "today": "2026-11-15"}))

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

    def test_only_headers_the_layout_copies_are_read(self):
        root, product = self.product({"a/x.h": comment(tag("UI-A1")), "b/y.h": comment(tag("UI-Z9")),
                                      "a/z.c": comment(tag("UI-Z8")), "third_party/q.h": comment(tag("UI-Z7")),
                                      "gate/q.h": comment(tag("UI-Z6")), "a/.git/q.h": comment(tag("UI-Z5")),
                                      "a/X.H": "/* DISAGREEMENTS */"}, include='["a/**", "third_party/**", "gate/**"]')
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (1, "ui-deviations: FAIL (1 findings)\n"
            '  {"entries":1,"line":1,"path":"a/X.H","rule":"deviation-untagged","severity":"error","tags":0}\n'))
    def test_a_symlinked_header_or_directory_that_would_be_graded_is_a_finding(self):
        root, product = self.product({"a/real.h": comment(tag("UI-A1")), "outside.h": comment(tag("UI-Z9")), "other/q.h": "int q;\n"})
        os.symlink(str(root / "outside.h"), str(root / "a" / "link.h"))
        os.symlink(str(root / "other"), str(root / "a" / "dir"))
        out = self.run_cli(root, product)
        self.assertEqual(out.code, 1)
        self.assertEqual(out.stdout, "ui-deviations: FAIL (2 findings)\n"
                         '  {"line":0,"path":"a/dir","rule":"deviation-malformed","severity":"error","why":"symlink"}\n'
                         '  {"line":0,"path":"a/link.h","rule":"deviation-malformed","severity":"error","why":"symlink"}\n')

    def test_bad_inputs_are_exit_2_with_one_line_and_no_traceback(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        cases = {
            "bad date": (root, product, "2026-02-30"),
            "date format": (root, product, "15/11/2026"),
            "no root": (self.tmp / "nope", product, "2026-11-15"),
            "no product": (root, self.tmp / "nope.toml", "2026-11-15"),
        }
        for name, (r, p, today) in cases.items():
            with self.subTest(name=name):
                out = self.run_cli(r, p, today)
                self.assertEqual(out.code, 2)
                self.assertEqual(out.stdout, "")
                self.assertTrue(out.stderr.startswith("rigor: internal error: "), out.stderr)
                self.assertNotIn("Traceback", out.stderr)

    def test_a_missing_or_broken_baseline_is_exit_2(self):
        root, product = self.product({"a/x.h": "int a;\n"})
        (product.parent / "ui" / "deviations.toml").unlink()
        out = self.run_cli(root, product)
        self.assertEqual(out.code, 2)
        self.assertNotIn("Traceback", out.stderr)
        (product.parent / "ui" / "deviations.toml").write_text("x = = 1")
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (2, ""))
        self.assertIn("deviations.toml", out.stderr)
        self.assertNotIn("Traceback", out.stderr)

    def test_a_non_utf8_header_is_a_finding_not_a_crash(self):
        root, product = self.product({"a/x.h": b"/* \xff */"})
        out = self.run_cli(root, product)
        self.assertEqual((out.code, out.stdout), (1, "ui-deviations: FAIL (2 findings)\n"
            '  {"id":"UI-A1","rule":"deviation-removed","severity":"info"}\n'
            '  {"line":1,"path":"a/x.h","rule":"deviation-malformed","severity":"error","why":"not-utf-8"}\n'))

    def test_the_committed_business_apps_baseline_with_a_clean_tree(self):
        root = self.sub("tree")
        (root / "apps").mkdir()
        (root / "apps" / "x.h").write_text("int a;\n")
        out = run_rigor(["ui-deviations", "--root", root, "--product", HERE.parent.parent / "products" / "business-apps" / "product.toml",
                         "--today", "2026-11-15"])
        self.assertEqual((out.code, out.stdout), (0, "ui-deviations: PASS (0 findings)\n"))


if __name__ == "__main__":
    unittest.main()
