"""Tests for the shared plumbing: JSON, findings, CLI error handling."""

import json
import os
from argparse import Namespace
from unittest import mock

from rigor_lib import cli, findings, jsonio
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


class MainExitCodeTests(TempDirTestCase):
    """A handler that forgets to return 0 or 1 must not turn into exit 0."""

    def main_with_handler(self, handler):
        parser = mock.Mock()
        parser.parse_args.return_value = Namespace(handler=handler, out=None, gate_id=None)
        with mock.patch.object(cli, "build_parser", return_value=parser):
            return cli.main([])

    def test_handler_returning_none_is_exit_2(self):
        self.assertEqual(self.main_with_handler(lambda args: None), 2)

    def test_handler_returning_other_numbers_is_exit_2(self):
        for value in (2, 3, -1, True, "0"):
            self.assertEqual(self.main_with_handler(lambda args, v=value: v), 2, value)

    def test_handler_returning_0_or_1_passes_through(self):
        self.assertEqual(self.main_with_handler(lambda args: 0), 0)
        self.assertEqual(self.main_with_handler(lambda args: 1), 1)

    def test_handler_raising_anything_is_exit_2(self):
        def boom(args):
            raise RuntimeError("boom")
        self.assertEqual(self.main_with_handler(boom), 2)


class WriteAtomicTests(TempDirTestCase):
    def test_writes_bytes_and_leaves_no_temp_files(self):
        target = self.tmp / "out.json"
        jsonio.write_atomic(target, b"data\n")
        self.assertEqual(target.read_bytes(), b"data\n")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["out.json"])

    def test_replaces_existing_file(self):
        target = self.tmp / "out.json"
        target.write_text("old")
        jsonio.write_atomic(target, b"new")
        self.assertEqual(target.read_bytes(), b"new")

    def test_failure_leaves_no_temp_files(self):
        with self.assertRaises(OSError):
            jsonio.write_atomic(self.tmp / "missing-dir" / "out.json", b"x")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_replace_failure_cleans_up_the_temp_file(self):
        target = self.tmp / "is-a-directory"
        target.mkdir()
        with self.assertRaises(OSError):
            jsonio.write_atomic(target, b"x")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["is-a-directory"])

    def test_file_is_world_readable(self):
        target = self.tmp / "out.json"
        jsonio.write_atomic(target, b"x")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)
