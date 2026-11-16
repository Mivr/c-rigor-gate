"""U13: the ratchet of `rigor_lib.ui_deviations` (new / changed / over-cap / removed / expired / duplicate), the untagged and
missing sections, misplaced files, the two loaders, the judge hook, the real headers (copies under data/ui_deviations/) and
the `rigor ui-deviations` command."""

import datetime
import hashlib
import json
import random
import unittest
import tomllib
from pathlib import Path
from types import MappingProxyType

from rigor_lib import ui_deviations as ud
from rigor_lib import ui_deviations_baseline as ub
from rigor_lib.errors import InternalError
from tests.helpers import TempDirTestCase
from tests.test_ui_deviations import PREFIX, TODAY, block, tag

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "ui_deviations"
PRODUCT_DIR = HERE.parent.parent / "products" / "business-apps"
# The real headers and what the section reader must find in each (counted by hand from the files): (name, heading line, entries).
HEADERS = (("screens.h", 180, 12), ("selftest.h", 75, 3), ("notices.h", 205, 9), ("vstate.h", 29, 7))
EMPTY = ub.Expectation("business-apps", MappingProxyType({}), MappingProxyType({}))


def accepted_for(path, *texts):
    """{id: (until, sha256)} computed here, from the literal fields, not by the implementation."""
    out = {}
    for text in texts:
        got = ud.scan_file(path, ("/* %s */" % text).encode(), ud.Context(PREFIX, TODAY)).tags[0]
        canonical = json.dumps({"id": got.id, "oracle": got.oracle, "state": list(got.states), "reason": got.reason,
                                "link": got.link, "until": got.until, "path": path}, sort_keys=True, separators=(",", ":")) + "\n"
        out[got.id] = (got.until, hashlib.sha256(canonical.encode("ascii")).hexdigest())
    return out


def base(cap=10, *texts, accepted=None, path="a.h"):
    pins = accepted_for(path, *texts) if accepted is None else accepted
    return ub.Baseline("business-apps", cap, MappingProxyType(pins), PREFIX)


def expect(**headers):
    names = {k.replace("_", "/") + ".h": v for k, v in headers.items()}
    return ub.Expectation("business-apps", MappingProxyType(names),
                          MappingProxyType({k: tuple("e%d" % i for i in range(v)) for k, v in names.items()}))


def comment(*tags):
    return block(*tags)


def run(files, baseline=None, expectation=EMPTY, today=TODAY):
    return ud.analyse([(p, t if t is None else t.encode()) for p, t in files],
                      base(0) if baseline is None else baseline, expectation, today)


def rules(found):
    return sorted((f["rule"], f.get("id", f.get("path", ""))) for f in found)


class Ratchet(TempDirTestCase):
    def test_no_tags_and_an_empty_baseline_is_clean(self):
        self.assertEqual(run([("a.h", "int x;\n")]), ((), ()))

    def test_a_tag_outside_the_baseline_is_new(self):
        tags, found = run([("a.h", "\n" + comment(tag("UI-A1")))], base(1))
        self.assertEqual([t.id for t in tags], ["UI-A1"])
        self.assertEqual(found, ({"rule": "deviation-new", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A1"},))

    def test_an_accepted_tag_is_clean_and_one_above_the_cap_is_over(self):
        first, second = tag("UI-A1"), tag("UI-A2")
        self.assertEqual(run([("a.h", comment(first, second))], base(2, first, second))[1], ())
        _, found = run([("a.h", comment(first, second))], base(1, first))
        self.assertEqual(found, ({"rule": "deviation-new", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A2"},
                                 {"rule": "deviation-over-cap", "severity": "error", "count": 2, "cap": 1}))

    def test_a_cap_of_zero_makes_every_tag_new_and_over_cap(self):
        _, found = run([("a.h", comment(tag("UI-A1")))], base(0))
        self.assertEqual(rules(found), [("deviation-new", "UI-A1"), ("deviation-over-cap", "")])

    def test_an_accepted_id_without_a_tag_is_removed_info(self):
        _, found = run([("a.h", comment(tag("UI-A1")))], base(3, tag("UI-A1"), tag("UI-B2")))
        self.assertEqual(found, ({"rule": "deviation-removed", "severity": "info", "id": "UI-B2"},))
        self.assertEqual(ud.GateResult("g", list(found), {}).status, "PASS")

    def test_any_change_of_an_accepted_tag_is_changed(self):
        pinned = base(1, tag("UI-A1"))
        changes = {"until pushed out": tag("UI-A1", until="2027-06-01"), "oracle": tag("UI-A1", oracle="another thing"),
                   "state": tag("UI-A1", state="welcome"), "reason": tag("UI-A1", reason="substrate"),
                   "link": tag("UI-A1", link="docs/other.md"), "until task": tag("UI-A1", until="T201")}
        for name, text in changes.items():
            with self.subTest(name=name):
                _, found = run([("a.h", comment(text))], pinned)
                self.assertEqual(found, ({"rule": "deviation-changed", "severity": "error", "path": "a.h", "line": 2,
                                          "id": "UI-A1"},))
        self.assertEqual(run([("a.h", comment(tag("UI-A1")))], pinned)[1], ())

    def test_a_tag_moved_to_another_header_is_changed(self):
        _, found = run([("b.h", comment(tag("UI-A1")))], base(1, tag("UI-A1"), path="a.h"))
        self.assertEqual(found, ({"rule": "deviation-changed", "severity": "error", "path": "b.h", "line": 2, "id": "UI-A1"},))
        self.assertEqual(run([("a.h", comment(tag("UI-A1")))], base(1, tag("UI-A1"), path="a.h"))[1], ())

    def test_the_canonical_form_is_pinned_by_a_literal_hash(self):
        text = '@deviation(UI-A1, oracle="o", state="s1,s2", reason="substrate", link="l", until="T100")'
        canonical = '{"id":"UI-A1","link":"l","oracle":"o","path":"a.h","reason":"substrate","state":["s1","s2"],"until":"T100"}\n'
        got = ud.scan_file("a.h", ("/* %s */" % text).encode(), ud.Context(PREFIX, TODAY)).tags[0]
        self.assertEqual(ud.canonical_bytes(got).decode(), canonical)
        self.assertEqual(ud.canonical_sha256(got), hashlib.sha256(canonical.encode()).hexdigest())

    def test_the_same_order_of_fields_or_spacing_does_not_change_the_hash(self):
        reordered = '@deviation(UI-A1, until="T200", link="docs/lockers/ui-look.md#4.3", reason="intentional", state="welcome,choose", oracle="welcome.slint idle echo")'
        self.assertEqual(run([("a.h", comment(reordered))], base(1, tag("UI-A1")))[1], ())

    def test_an_id_reused_after_removal_with_other_content_is_changed_not_new_or_clean(self):
        pinned = base(1, tag("UI-A1"))
        self.assertEqual(run([("a.h", "int x;\n")], pinned)[1], ({"rule": "deviation-removed", "severity": "info", "id": "UI-A1"},))
        _, found = run([("a.h", comment(tag("UI-A1", oracle="a different deviation")))], pinned)
        self.assertEqual([f["rule"] for f in found], ["deviation-changed"])

    def test_duplicate_ids_in_one_file_and_across_files(self):
        _, found = run([("b.h", comment(tag("UI-A1"))), ("a.h", comment(tag("UI-A1"), tag("UI-A1")))], base(1, tag("UI-A1")))
        self.assertEqual(found, (
            {"rule": "deviation-malformed", "severity": "error", "path": "a.h", "line": 3, "id": "UI-A1",
             "why": "duplicate-id", "first": "a.h:2"},
            {"rule": "deviation-malformed", "severity": "error", "path": "b.h", "line": 2, "id": "UI-A1",
             "why": "duplicate-id", "first": "a.h:2"}))

    def test_expired_against_the_passed_date_only(self):
        for until, expired in (("2026-11-14", True), ("2026-11-15", False), ("2026-11-16", False), ("T104", False),
                               ("2020-01-01", True)):
            with self.subTest(until=until):
                text = tag("UI-A1", until=until)
                _, found = run([("a.h", comment(text))], base(1, text))
                self.assertEqual(found, ({"rule": "deviation-expired", "severity": "error", "path": "a.h", "line": 2,
                                          "id": "UI-A1", "until": until},) if expired else ())

    def test_the_same_files_judge_differently_on_another_date(self):
        text = tag("UI-A1", until="2026-12-01")
        files = [("a.h", comment(text))]
        self.assertEqual(run(files, base(1, text), today=datetime.date(2026, 12, 1))[1], ())
        self.assertEqual(len(run(files, base(1, text), today=datetime.date(2026, 12, 2))[1]), 1)

    def test_a_malformed_tag_is_a_finding_and_is_not_counted_as_a_tag(self):
        tags, found = run([("a.h", comment(tag("UI-A1", reason="x")))], base(0))
        self.assertEqual((tags, [f["rule"] for f in found]), ((), ["deviation-malformed"]))

    def test_a_file_over_the_size_cap_is_a_finding(self):
        self.assertEqual(run([("a.h", None)])[1], ({"rule": "deviation-malformed", "severity": "error", "path": "a.h", "line": 0,
                                                    "why": "file-too-large"},))

    def test_discover_reads_no_more_than_the_cap(self):
        root = self.sub("t")
        (root / "a").mkdir()
        (root / "a" / "big.h").write_bytes(b"x" * 11)
        (root / "a" / "ok.h").write_bytes(b"x" * 10)
        old, ud.MAX_BYTES = ud.MAX_BYTES, 10
        try:
            files, problems = ud.discover(str(root), _config(self.tmp, '["a/**"]'))
        finally:
            ud.MAX_BYTES = old
        self.assertEqual((files, problems), ([("a/big.h", None), ("a/ok.h", b"x" * 10)], []))


def _config(tmp, include):
    from rigor_lib import product_layout
    path = tmp / "pc.toml"
    path.write_text('name = "p"\n[layout]\ninclude = %s\n' % include)
    return product_layout.load_product(str(path))


class Prose(TempDirTestCase):
    SECTION = "/*\n * Deviations:\n * L1 a\n * L2 b\n */\n"

    def test_untagged_entries_are_a_finding_with_the_counts(self):
        _, found = run([("a.h", self.SECTION)])
        self.assertEqual(found, ({"rule": "deviation-untagged", "severity": "error", "path": "a.h", "line": 2, "entries": 2,
                                  "detected": 2, "acknowledged": 0, "tags": 0},))

    def test_one_distinct_tag_per_entry_clears_it(self):
        texts = [tag("UI-A1"), tag("UI-A2")]
        self.assertEqual(run([("a.h", self.SECTION + comment(*texts))], base(2, *texts))[1], ())
        _, found = run([("a.h", self.SECTION + comment(texts[0]))], base(2, *texts))
        self.assertEqual([(f["rule"], f.get("tags")) for f in found if f["rule"] != "deviation-removed"], [("deviation-untagged", 1)])

    def test_the_same_id_twice_counts_once(self):
        text = tag("UI-A1")
        _, found = run([("a.h", self.SECTION + comment(text, text))], base(2, text))
        self.assertEqual(sorted((f["rule"], f.get("tags", 0)) for f in found), [("deviation-malformed", 0), ("deviation-untagged", 1)])

    def test_a_section_with_prose_and_no_label_is_unlabelled_not_one_entry(self):
        text = "/* DISAGREEMENTS (Rust wins). It differs here. */\n"
        tags, found = run([("a.h", text)])
        self.assertEqual(found, ({"rule": "deviation-unlabelled", "severity": "error", "path": "a.h", "line": 1},))

    def test_an_unlabelled_section_does_not_hide_a_labelled_one(self):
        text = "/* Deviations: prose only */\nint x;\n" + self.SECTION
        self.assertEqual(rules(run([("a.h", text)])[1]), [("deviation-unlabelled", "a.h"), ("deviation-untagged", "a.h")])

    def test_an_acknowledged_count_above_the_detected_one_is_the_requirement(self):
        _, found = run([("a.h", self.SECTION)], expectation=expect(a=5))
        self.assertEqual([(f["entries"], f["detected"], f["acknowledged"], f["tags"]) for f in found], [(5, 2, 5, 0)])
        texts = [tag("UI-A1"), tag("UI-A2")]
        _, found = run([("a.h", self.SECTION + comment(*texts))], base(2, *texts), expect(a=5))
        self.assertEqual([(f["entries"], f["detected"], f["acknowledged"], f["tags"]) for f in found], [(5, 2, 5, 2)])
        _, found = run([("a.h", self.SECTION)], expectation=expect(a=1))
        self.assertEqual([(f["entries"], f["detected"], f["acknowledged"]) for f in found], [(2, 2, 1)])

    def test_a_listed_header_whose_section_cannot_be_detected_is_section_missing(self):
        _, found = run([("a.h", "int x;\n")], expectation=expect(a=2))
        self.assertEqual(found, ({"rule": "deviation-section-missing", "severity": "error", "path": "a.h", "acknowledged": 2,
                                  "tags": 0},))
        _, found = run([("a.h", "/* Notes:\n 1. renamed */\n")], expectation=expect(a=2))
        self.assertEqual([f["rule"] for f in found], ["deviation-section-missing"])

    def test_tags_covering_the_acknowledged_entries_settle_a_missing_section(self):
        texts = [tag("UI-A1"), tag("UI-A2")]
        self.assertEqual(run([("a.h", comment(*texts))], base(2, *texts), expect(a=2))[1], ())
        _, found = run([("a.h", comment(texts[0]))], base(2, *texts), expect(a=2))
        self.assertEqual([f["rule"] for f in found if f["rule"] != "deviation-removed"], ["deviation-section-missing"])

    def test_a_listed_header_that_is_gone_is_section_missing(self):
        _, found = run([("b.h", "int x;\n")], expectation=expect(a=2))
        self.assertEqual(found, ({"rule": "deviation-section-missing", "severity": "error", "path": "a.h", "acknowledged": 2,
                                  "tags": 0, "header": "absent"},))

    def test_a_listed_non_header_is_not_a_present_header(self):
        _, found = run([("a.c", "int x;\n")], expectation=expect(a=2))
        self.assertEqual([f["rule"] for f in found], ["deviation-section-missing"])

    def test_a_section_or_tag_in_a_file_that_is_not_a_header_is_misplaced(self):
        for name in ("a.c", "a.inc", "a.hh", "a.hpp", "a.cc", "a.def", "a.H.c"):
            with self.subTest(name=name):
                _, found = run([(name, self.SECTION + comment(tag("UI-A1")))], base(1, tag("UI-A1"), path=name))
                self.assertEqual(found, ({"rule": "deviation-misplaced", "severity": "error", "path": name, "line": 7,
                                          "what": "tag", "id": "UI-A1"},
                                         {"rule": "deviation-misplaced", "severity": "error", "path": name, "line": 2,
                                          "what": "section"}))
        self.assertEqual(run([("a.c", "/* ordinary */\nint x;\n")]), ((), ()))
        self.assertEqual(run([("a.H", self.SECTION)])[1][0]["rule"], "deviation-untagged")      # `.H` is a header

    def test_a_tag_in_a_non_header_still_counts_against_the_baseline(self):
        _, found = run([("a.c", comment(tag("UI-A1")))], base(0))
        self.assertEqual(sorted(f["rule"] for f in found), ["deviation-misplaced", "deviation-new", "deviation-over-cap"])

    def test_malformed_tags_in_a_non_header_are_malformed(self):
        self.assertEqual([f["rule"] for f in run([("a.c", "/* @Deviation(x) */")])[1]], ["deviation-malformed"])


class Moves(TempDirTestCase):
    SECTION = "/*\n * Deviations:\n * L1 a\n * L2 b\n */\n"

    def test_a_listed_path_that_exists_with_another_case_or_extension_names_the_real_file(self):
        for actual in ("a/X.H", "A/x.h", "a/x.hh", "a/x.c", "a/X.h"):
            with self.subTest(actual=actual):
                _, found = run([(actual, "int x;\n")], expectation=expect(a_x=2))
                self.assertEqual(found, ({"rule": "deviation-section-missing", "severity": "error", "path": "a/x.h", "acknowledged": 2,
                                          "tags": 0, "header": "absent", "actual": actual},))
        _, found = run([("b/y.h", "int x;\n")], expectation=expect(a_x=2))
        self.assertNotIn("actual", found[0])

    def test_a_case_variant_does_not_satisfy_the_listing(self):
        texts = [tag("UI-A1"), tag("UI-A2")]
        _, found = run([("a/X.H", comment(*texts))], base(2, *texts, path="a/X.H"), expect(a_x=2))
        self.assertEqual([f["rule"] for f in found], ["deviation-section-missing"])

    def test_a_section_that_continues_after_code_is_a_split(self):
        text = self.SECTION + "int x;\n/*\n * L3 c\n */\n"
        _, found = run([("a.h", text)])
        self.assertEqual(sorted((f["rule"], f["line"]) for f in found), [("deviation-section-split", 8), ("deviation-untagged", 2)])
        self.assertEqual(run([("a.h", self.SECTION + "int x;\n/* ordinary */\n")])[1][0]["rule"], "deviation-untagged")

    def test_a_confusable_heading_is_a_finding_and_hides_nothing_else(self):
        _, found = run([("a.h", "/*\n * Dis\u0430greements:\n * plain\n */\n")])
        self.assertEqual(found, ({"rule": "deviation-malformed", "severity": "error", "path": "a.h", "line": 2, "why": "confusable"},))


class Hook(TempDirTestCase):
    def tags(self):
        return run([("a.h", comment(tag("UI-A1"), tag("UI-B2"), tag("UI-C3")))])[0]

    def test_the_hook_marks_pinned_and_stale(self):
        found = ud.judge_tags(self.tags(), frozenset({"UI-A1", "UI-C3", "UI-NOTAG-1"}))
        self.assertEqual(found, (
            {"rule": "pinned-deviation", "severity": "info", "path": "a.h", "line": 2, "id": "UI-A1"},
            {"rule": "deviation-stale", "severity": "error", "path": "a.h", "line": 3, "id": "UI-B2"},
            {"rule": "pinned-deviation", "severity": "info", "path": "a.h", "line": 4, "id": "UI-C3"}))
        self.assertEqual(ud.judge_tags((), set()), ())

    def test_the_hook_takes_any_iterable_of_tags(self):
        tags = self.tags()
        want = ud.judge_tags(tags, {"UI-B2"})
        for source in (list(tags), iter(tags), (t for t in tags), tuple(reversed(tags)), set(tags)):
            with self.subTest(kind=type(source).__name__):
                self.assertEqual(ud.judge_tags(source, {"UI-B2"}), want)

    def test_the_hook_refuses_a_wrong_argument(self):
        tags = self.tags()
        for tags_arg, div in ((tags, ["UI-A1"]), (tags, {1}), (tags, None), (tags, "UI-A1"), (({"id": "UI-A1"},), set()),
                              (5, set()), (None, set())):
            with self.subTest(div=div):
                with self.assertRaises(InternalError):
                    ud.judge_tags(tags_arg, div)


class Deterministic(TempDirTestCase):
    def test_the_result_does_not_depend_on_the_order_of_the_files(self):
        files = [("d/%d.h" % i, comment(tag("UI-A%d" % (i % 4)), tag("UI-B%d" % i, until="2020-01-01"))
                  + "/* Deviations:\n 1. a\n 2. b\n 3. c */\n") for i in range(8)]
        files.append(("e.h", "/* @deviation(oops */"))
        files.append(("f.c", comment(tag("UI-Q1"))))
        first = run(files, base(3, tag("UI-Q1"), path="f.c"), expect(d_0=2))
        for seed in range(6):
            shuffled = list(files)
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(run(shuffled, base(3, tag("UI-Q1"), path="f.c"), expect(d_0=2)), first)
        result = ud.GateResult(ud.GATE_ID, list(first[1]), {})
        self.assertEqual(result.to_json_bytes(), ud.GateResult(ud.GATE_ID, list(reversed(first[1])), {}).to_json_bytes())


class Loaders(TempDirTestCase):
    GOOD = ('schema = "ui-deviations/3"\nproduct = "business-apps"\ncap = 2\nreference_bug_link_prefix = "https://x/i/"\n'
            '[accepted."UI-A1"]\nuntil = "T200"\nsha256 = "%s"\n[accepted."UI-B2"]\nuntil = "2027-01-01"\nsha256 = "%s"\n' % ("0" * 64, "a" * 64))

    def load(self, text, product="business-apps"):
        path = self.tmp / "deviations.toml"
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return ub.load_baseline(str(path), product, TODAY)

    def test_the_good_file_loads_immutably(self):
        loaded = self.load(self.GOOD)
        self.assertEqual((loaded.cap, dict(loaded.accepted), loaded.link_prefix),
                         (2, {"UI-A1": ("T200", "0" * 64), "UI-B2": ("2027-01-01", "a" * 64)}, "https://x/i/"))
        with self.assertRaises(TypeError):
            loaded.accepted["UI-C3"] = ("T1", "0" * 64)

    def test_every_defect_is_exit_2(self):
        good = self.GOOD
        head, accepted = good.split("[accepted.", 1)
        accepted = "[accepted." + accepted
        bad = {
            "unknown key": "extra = 1\n" + good, "missing key": good.replace("cap = 2\n", ""),
            "the old pattern key": good.replace("[accepted", "reference_bug_link_pattern = 'x'\n[accepted", 1),
            "wrong schema": good.replace("ui-deviations/3", "ui-deviations/2"),
            "other product": good.replace('"business-apps"', '"annas-c"'),
            "cap string": good.replace("cap = 2", 'cap = "2"'), "cap bool": good.replace("cap = 2", "cap = true"),
            "cap negative": good.replace("cap = 2", "cap = -1"), "cap float": good.replace("cap = 2", "cap = 2.0"),
            "cap above the bound": good.replace("cap = 2", "cap = 1001"), "above the cap": good.replace("cap = 2", "cap = 1"),
            "prefix not https": good.replace('"https://x/i/"', '"http://x/i/"'), "prefix not a string": good.replace('"https://x/i/"', "1"),
            "prefix with a space": good.replace('"https://x/i/"', '"https://x/ i/"'),
            "prefix without the final slash": good.replace('"https://x/i/"', '"https://x/i"'),
            "prefix too long": good.replace('"https://x/i/"', '"https://x/' + "a" * 200 + '/"'),
            "accepted not a table": head + "accepted = []\n",
            "accepted bad id": head + accepted.replace("UI-A1", "ui-a1"), "accepted unsorted": head + accepted.replace("UI-A1", "UI-Z1"),
            "accepted extra key": head + accepted.replace('until = "T200"', 'until = "T200"\nx = 1'),
            "accepted missing sha": head + accepted.replace('sha256 = "%s"\n' % ("0" * 64), ""),
            "accepted bad until": head + accepted.replace('"T200"', '"NEVER-1"'), "accepted until type": head + accepted.replace('"T200"', "5"),
            "accepted until not a calendar date": head + accepted.replace('"T200"', '"2027-02-29"'),
            "accepted until beyond the horizon": head + accepted.replace('"T200"', '"2027-11-18"'),
            "accepted until far away": head + accepted.replace('"T200"', '"2099-01-01"'),
            "accepted sha uppercase": head + accepted.replace("0" * 64, "A" * 64), "accepted sha short": head + accepted.replace("0" * 64, "0" * 63),
            "accepted entry not a table": head + '[accepted]\n"UI-A1" = 1\n',
            "not toml": "cap = = 2\n", "duplicate key": good + "cap = 3\n", "not utf-8": b"\xff\xfe",
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(InternalError) as caught:
                    self.load(text)
                self.assertIn("deviations.toml", str(caught.exception))
                for word in ("accepted", "cap", "prefix"):
                    if name.startswith(word) or name == "above the " + word:
                        self.assertIn(word, str(caught.exception))
        self.assertEqual(self.load(head + "[accepted]\n").accepted, {})
        self.assertEqual(sorted(self.load(good).accepted), ["UI-A1", "UI-B2"])

    def test_the_until_horizon_is_checked_against_the_date_passed_in(self):
        late = self.GOOD.replace("2027-01-01", "2027-11-16")
        self.assertEqual(self.load(late).accepted["UI-B2"][0], "2027-11-16")
        path = self.tmp / "deviations.toml"
        with self.assertRaises(InternalError):
            ub.load_baseline(str(path), "business-apps", datetime.date(2026, 11, 14))

    def test_the_committed_baseline_is_empty_with_cap_zero_and_the_club_apps_prefix(self):
        got = ub.load_baseline(str(PRODUCT_DIR / "ui" / "deviations.toml"), "business-apps", TODAY)
        self.assertEqual((got.cap, dict(got.accepted), got.link_prefix), (0, {}, "https://github.com/Mivr/club-apps/issues/"))

    def expectation(self, text):
        path = self.tmp / "sections.toml"
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return ub.load_expectation(str(path), "business-apps")

    def test_the_expectation_loader_is_strict(self):
        good = ('schema = "ui-deviation-sections/2"\nproduct = "business-apps"\n[headers."a/b.h"]\ncount = 2\nlabels = ["D1", "D2"]\n'
                '[headers."a/c.h"]\ncount = 1\nlabels = ["N1"]\n')
        got = self.expectation(good)
        self.assertEqual((dict(got.headers), dict(got.labels)), ({"a/b.h": 2, "a/c.h": 1}, {"a/b.h": ("D1", "D2"), "a/c.h": ("N1",)}))
        bad = {
            "unknown key": "x = 1\n" + good, "missing headers": good.split("[headers")[0], "wrong schema": good.replace("/2", "/1"),
            "other product": good.replace("business-apps", "p"),
            "unsorted": good.replace('"a/b.h"', '"a/d.h"'), "count zero": good.replace("count = 2", "count = 0"),
            "count bool": good.replace("count = 1", "count = true"), "count string": good.replace("count = 2", 'count = "2"'),
            "count not the number of labels": good.replace("count = 2", "count = 3"),
            "count too many": good.replace("count = 2", "count = 1000"),
            "no labels": good.replace('labels = ["N1"]', "labels = []").replace("count = 1", "count = 0"),
            "duplicate labels": good.replace('["D1", "D2"]', '["D1", "D1"]'), "empty label": good.replace('"D2"', '""'),
            "padded label": good.replace('"D2"', '" D2"'), "label not a string": good.replace('"D2"', "2"),
            "label too long": good.replace('"D2"', '"' + "x" * 81 + '"'), "labels not a list": good.replace('["D1", "D2"]', '"D1"'),
            "extra entry key": good.replace("count = 2", "count = 2\nx = 1"), "missing labels": good.replace('labels = ["N1"]\n', ""),
            "path not .h": good.replace('"a/c.h"', '"a/c.c"'), "path upper case extension": good.replace('"a/c.h"', '"a/c.H"'),
            "absolute": good.replace('"a/b.h"', '"/a/b.h"'), "dot segment": good.replace('"a/b.h"', '"a/../b.h"'),
            "not normalised": good.replace('"a/b.h"', '"a//b.h"'), "empty path": good.replace('"a/b.h"', '""'),
            "entry not a table": good.split("[headers")[0] + '[headers]\n"a/b.h" = 2\n', "headers a list": good.split("[headers")[0] + "headers = []\n",
            "not toml": "x = = 1", "not utf-8": b"\xff",
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                with self.assertRaises(InternalError):
                    self.expectation(text)

    def test_the_committed_expectation_lists_the_read_headers_with_their_labels(self):
        got = ub.load_expectation(str(PRODUCT_DIR / "ui" / "deviation-sections.toml"), "business-apps")
        table = tomllib.loads((PRODUCT_DIR / "ui" / "deviation-sections.toml").read_text())["headers"]
        self.assertEqual({k: v["count"] for k, v in table.items()}, dict(got.headers))
        self.assertEqual({k: tuple(v["labels"]) for k, v in table.items()}, dict(got.labels))
        want = {"apps/lockers/lkui/notices/notices.h": ["N%d" % k for k in range(1, 10)],
                "apps/lockers/lkapp/wire/wire.h": ["D%d" % k for k in range(1, 9)],
                "apps/lockers/lkrx/visit/visit.h": ["DISAGREE-1", "DISAGREE-2", "DISAGREE-3", "DISAGREE-4", "GAP-V1", "GAP-V2", "GAP-V3"],
                "apps/lockers/lk/codesfile/codesfile.h": ["D1-D4", "D5", "D6", "D7"],
                "apps/lockers/lkadp/codeshttp/codeshttp.h": ["N1", "N2", "N3", "N4", "N5", "N6", "N8"]}
        for name, labels in want.items():
            self.assertEqual(list(got.labels[name]), labels)
        self.assertEqual((len(table), sum(got.headers.values())), (40, 214))
        self.assertTrue(all(name.endswith(".h") for name in table))


class RealHeaders(TempDirTestCase):
    def read(self, name):
        return (DATA / name).read_bytes()

    def test_the_copies_are_the_recorded_bytes(self):
        for name in [n for n, _, _ in HEADERS] + ["preflight.h", "wire.h", "visit.h", "codesfile.h"]:
            with self.subTest(name=name):
                recorded = (DATA / (name + ".sha256")).read_text(encoding="ascii").strip()
                self.assertEqual(len(recorded), 64)
                self.assertEqual(hashlib.sha256(self.read(name)).hexdigest(), recorded)

    def test_each_real_header_has_its_exact_heading_entry_count_and_no_tag(self):
        for name, line, entries in HEADERS:
            with self.subTest(name=name):
                got = ud.scan_file(name, self.read(name), ud.Context(PREFIX, TODAY))
                self.assertEqual((got.tags, got.bad, got.sections), ((), (), ((line, entries),)))
                _, found = ud.analyse([(name, self.read(name))], base(0), EMPTY, TODAY)
                self.assertEqual(found, ({"rule": "deviation-untagged", "severity": "error", "path": name, "line": line,
                                          "entries": entries, "detected": entries, "acknowledged": 0, "tags": 0},))

    def test_wire_visit_and_codesfile_do_not_count_cross_references_as_entries(self):
        for name, sections in (("wire.h", ((251, 8),)), ("visit.h", ((148, 7),)), ("codesfile.h", ((10, 8), (251, 4)))):
            with self.subTest(name=name):
                got = ud.scan_file(name, self.read(name), ud.Context(PREFIX, TODAY))
                self.assertEqual((got.tags, got.bad, got.sections, got.splits), ((), (), sections, ()))

    def test_the_prose_only_header_is_unlabelled(self):
        _, found = ud.analyse([("preflight.h", self.read("preflight.h"))], base(0), EMPTY, TODAY)
        self.assertEqual(found, ({"rule": "deviation-unlabelled", "severity": "error", "path": "preflight.h", "line": 139},))

    def test_one_tag_per_entry_clears_the_finding_and_one_fewer_does_not(self):
        for name, _, entries in HEADERS:
            texts = [tag("UI-%s%d" % (name[0].upper(), k)) for k in range(entries)]
            full = self.read(name).decode() + comment(*texts)
            short = self.read(name).decode() + comment(*texts[:-1])
            with self.subTest(name=name):
                self.assertEqual(run([(name, full)], base(entries, *texts, path=name))[1], ())
                _, found = run([(name, short)], base(entries, *texts[:-1], path=name))
                self.assertEqual([(f["rule"], f["entries"], f["tags"]) for f in found], [("deviation-untagged", entries, entries - 1)])

    def test_a_malformed_tag_does_not_count_towards_the_entries(self):
        texts = [tag("UI-S1"), tag("UI-S2")]
        text = self.read("selftest.h").decode() + comment(*texts, tag("UI-S3", reason="bogus"))
        _, found = run([("selftest.h", text)], base(3, *texts, path="selftest.h"))
        self.assertEqual(sorted((f["rule"], f.get("tags")) for f in found if f["rule"] != "deviation-removed"),
                         [("deviation-malformed", None), ("deviation-untagged", 2)])
