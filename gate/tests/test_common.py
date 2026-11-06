"""Tests for the shared plumbing: JSON, findings, CLI error handling."""

import json

from rigor_lib import findings, jsonio
from tests.helpers import RIGOR, TempDirTestCase, read_json, run_rigor


class CanonicalJsonTests(TempDirTestCase):
    def test_sorted_compact_with_trailing_newline(self):
        data = jsonio.canonical_dumps({"b": 1, "a": [1, 2]})
        self.assertEqual(data, b'{"a":[1,2],"b":1}\n')

    def test_non_ascii_is_escaped(self):
        self.assertEqual(jsonio.canonical_dumps({"k": "\u00e9"}), b'{"k":"\\u00e9"}\n')

    def test_nan_is_refused(self):
        with self.assertRaises(ValueError):
            jsonio.canonical_dumps({"k": float("nan")})


class StrictLoadsTests(TempDirTestCase):
    def test_accepts_plain_json(self):
        self.assertEqual(jsonio.strict_loads(b'{"a": [1, 2.5, null]}'), {"a": [1, 2.5, None]})

    def test_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            jsonio.strict_loads(b'{"a": 1, "a": 2}')

    def test_rejects_nan_and_infinity(self):
        for text in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}'):
            with self.assertRaises(ValueError):
                jsonio.strict_loads(text)

    def test_rejects_invalid_json(self):
        with self.assertRaises(ValueError):
            jsonio.strict_loads(b"{not json")

    def test_rejects_invalid_utf8(self):
        with self.assertRaises(ValueError):
            jsonio.strict_loads(b'{"a": "\xff"}')

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            jsonio.strict_loads(b"")


class FindingTests(TempDirTestCase):
    def test_default_severity_is_error(self):
        item = findings.finding("some-rule", path="a")
        self.assertEqual(item, {"rule": "some-rule", "severity": "error", "path": "a"})

    def test_info_only_result_passes(self):
        result = findings.GateResult("g", [findings.finding("x", severity="info")], {})
        self.assertEqual(result.status, "PASS")

    def test_any_error_makes_result_fail(self):
        result = findings.GateResult("g", [findings.finding("x", severity="info"),
                                           findings.finding("y")], {})
        self.assertEqual(result.status, "FAIL")

    def test_no_findings_passes(self):
        self.assertEqual(findings.GateResult("g", [], {}).status, "PASS")

    def test_unknown_severity_is_refused(self):
        with self.assertRaises(ValueError):
            findings.finding("x", severity="warn")

    def test_findings_are_sorted_deterministically(self):
        one = findings.GateResult("g", [findings.finding("b"), findings.finding("a")], {})
        two = findings.GateResult("g", [findings.finding("a"), findings.finding("b")], {})
        self.assertEqual(one.to_json_bytes(), two.to_json_bytes())
        parsed = json.loads(one.to_json_bytes())
        self.assertEqual([f["rule"] for f in parsed["findings"]], ["a", "b"])

    def test_metadata_does_not_change_findings_bytes(self):
        one = findings.GateResult("g", [findings.finding("a")], {"t": 1})
        two = findings.GateResult("g", [findings.finding("a")], {"t": 2})
        self.assertEqual(one.findings_bytes(), two.findings_bytes())


class CliFailClosedTests(TempDirTestCase):
    def test_entry_point_has_isolated_shebang(self):
        first = RIGOR.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first, "#!/usr/bin/env -S python3 -I")

    def test_entry_point_is_executable(self):
        self.assertTrue(RIGOR.stat().st_mode & 0o111)

    def test_no_arguments_is_exit_2(self):
        self.assertExit(run_rigor([]), 2)

    def test_unknown_subcommand_is_exit_2(self):
        self.assertExit(run_rigor(["frobnicate"]), 2)
