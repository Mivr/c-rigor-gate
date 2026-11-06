"""Tests for tools/lanes/buck2_stats.py (T022): real trimmed Buck2 event logs plus a few synthetic records."""

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "lanes" / "buck2_stats.py"
FIX = ROOT / "tools" / "lanes" / "fixtures" / "log"

spec = importlib.util.spec_from_file_location("buck2_stats", TOOL)
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)

TEST_LOG = "20261106-141145_test_516a6aaf-7962-40fe-ae00-5da20143f379_events.json-lines"
HIT_LOG = "20261106-141311_build_6fb06907-db50-4d5e-ba6c-35767bd70d3d_events.json-lines"
FAIL_LOG = "20261106-141423_build_73fe4f90-2512-438e-8db8-4a69335b1b10_events.json-lines"


def project_with(*names):
    """A temp project root whose buck-out/v2/log holds the named fixture logs and their command reports."""
    root = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/var/tmp"))
    logdir = Path(root, "buck-out", "v2", "log")
    logdir.mkdir(parents=True)
    for name in names:
        shutil.copy(FIX / name, logdir / name)
        trace = name.split("_")[2]
        shutil.copytree(FIX / trace, logdir / trace)
    return root


def row_of(name):
    root = project_with(name)
    try:
        rows = stats.collect(root)
    finally:
        shutil.rmtree(root)
    assert len(rows) == 1, rows
    return rows[0]


def action(kind_body, category="c_compile", ident="x.c", failed=False, size=10, worker=100, wall=200, queue=7):
    """A synthetic ActionExecution SpanEnd record (shape copied from a real log)."""
    cmd = {"details": {"signed_exit_code": 0, "command_kind": {"command": kind_body},
                       "metadata": {"wall_time_us": wall, "execution_time_us": worker, "queue_duration_us": queue,
                                    "input_materialization_duration_us": 3}}, "status": {"Success": {}}}
    body = {"key": {"owner": {"TargetLabel": {"label": {"package": "root//p", "name": "t"}}}},
            "name": {"category": category, "identifier": ident}, "failed": failed, "output_size": size,
            "commands": [cmd]}
    return span_end({"ActionExecution": body})


def span_end(data, dur=1, when=(100, 0)):
    return {"Event": {"timestamp": list(when), "trace_id": "T", "span_id": 1, "parent_id": 0,
                      "data": {"SpanEnd": {"duration_us": dur, "data": data}}}}


def snapshot(down, up, lookups, when=(100, 0)):
    snap = {"re_download_bytes": down, "re_upload_bytes": up, "re_action_cache_started": lookups}
    return {"Event": {"timestamp": list(when), "trace_id": "T", "span_id": 0, "parent_id": 0,
                      "data": {"Instant": {"data": {"Snapshot": snap}}}}}


HEADER = {"command_line_args": ["/bin/buck2", "build", "//a:b"], "trace_id": "T", "start_time": [99, 500000000]}


class RealLogRows(unittest.TestCase):
    def test_successful_test_command(self):
        r = row_of(TEST_LOG)
        self.assertEqual(r["args"], "test //selftest/scratch:t")
        self.assertEqual(r["exit_code"], 0)
        self.assertEqual((r["wall_ms"], r["command_ms"]), (3304, 2173))
        self.assertEqual(r["start_unix"], 1793974304.7217374)
        self.assertEqual(r["actions_total"], 7)  # the fixture keeps all executed actions and 2 command-less ones
        self.assertEqual(r["test_runs"], 1)
        self.assertEqual((r["executed_remote"], r["executed_local"], r["cache_hits"], r["cache_misses"]), (5, 0, 0, 5))
        self.assertEqual(r["actions_without_command"], 2)
        self.assertEqual(r["failed_actions"], 0)
        self.assertEqual(r["re_action_cache_lookups"], 4)
        self.assertEqual(r["dep_file_match_outcomes"], {"outcome_1": 4})
        self.assertEqual((r["remote_worker_us_sum"], r["remote_worker_us_max"]), (1173680, 320844))
        self.assertEqual((r["remote_queue_us_sum"], r["remote_queue_us_max"]), (22126, 17554))
        self.assertEqual((r["remote_wall_us_sum"], r["remote_wall_us_max"]), (1826593, 452050))
        self.assertEqual(r["remote_input_materialization_us_sum"], 232484)
        self.assertEqual((r["cas_uploaded_bytes"], r["cas_downloaded_bytes"]), (22790, 13634))
        self.assertEqual((r["reupload_bytes"], r["reupload_digests"]), (4840, 43))
        self.assertEqual(r["executed_output_bytes"], 10382)
        self.assertEqual(len(r["longest_actions"]), 5)
        self.assertEqual(r["longest_actions"][0],
                         {"worker_us": 320844, "category": "cxx_link_executable", "identifier": "",
                          "target": "root//selftest/scratch:t", "executor": "remote"})
        times = [a["worker_us"] for a in r["longest_actions"]]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_cache_hits_are_not_counted_as_spend(self):
        r = row_of(HIT_LOG)
        self.assertEqual((r["executed_remote"], r["cache_hits"], r["cache_misses"]), (0, 6, 0))
        self.assertEqual(r["cache_hits_by_type"], {"cache_hit_type_0": 6})
        self.assertEqual(r["remote_worker_us_sum"], 0)
        self.assertEqual(r["cached_worker_us_sum"], 122180559)
        self.assertEqual(r["executed_output_bytes"], 0)
        self.assertEqual(r["longest_actions"], [])
        self.assertEqual(r["actions_total"], 8)  # the fixture keeps 2 of 22 command-less actions
        self.assertEqual(r["actions_without_command"], 2)

    def test_failed_command(self):
        r = row_of(FAIL_LOG)
        self.assertEqual(r["exit_code"], 3)
        self.assertEqual(r["failed_actions"], 1)
        self.assertEqual(r["args"], "build //selftest/scratch/bad:bad")
        self.assertEqual((r["executed_remote"], r["cache_misses"]), (1, 1))
        self.assertEqual(r["longest_actions"][0]["identifier"], "bad.c")
        self.assertEqual(r["longest_actions"][0]["worker_us"], 265340)
        self.assertEqual(r["remote_worker_us_sum"], 265340)

    def test_missing_fields_are_null_not_zero(self):
        r = row_of(TEST_LOG)
        for key in ("remote_cpu_user_us", "remote_cpu_system_us", "materialized_bytes"):
            self.assertIsNone(r[key])


class SyntheticRecords(unittest.TestCase):
    def rows(self, *events, header=HEADER):
        return stats.summarize("/x/log_events.json-lines", [header] + list(events))

    def test_local_and_other_executors_and_dep_file_hit(self):
        r = self.rows(
            snapshot(1000, 2000, 5, (100, 0)),
            action({"LocalCommand": {}}, ident="a.c", worker=50),
            action({"WorkerCommand": {}}, ident="b.c", worker=70),
            action({"OmittedLocalCommand": {}}, ident="c.c"),
            action({"RemoteCommand": {"cache_hit": True, "cache_hit_type": 1}}, ident="d.c", worker=999),
            snapshot(1600, 2900, 8, (101, 0)),
        )
        self.assertEqual((r["executed_local"], r["executed_remote"], r["actions_other_executor"]), (2, 0, 1))
        self.assertEqual(r["cache_hits_by_type"], {"cache_hit_type_1": 1})
        self.assertEqual(r["cached_worker_us_sum"], 999)
        self.assertEqual(r["remote_worker_us_sum"], 120)  # local runs are timed too
        self.assertEqual((r["cas_downloaded_bytes"], r["cas_uploaded_bytes"], r["re_action_cache_lookups"]), (600, 900, 3))
        self.assertEqual([a["executor"] for a in r["longest_actions"]], ["local", "local"])
        self.assertEqual(r["wall_ms"], 1500)

    def test_top_five_sorted_and_ties_stable(self):
        evs = [action({"RemoteCommand": {"cache_hit": False}}, ident="f%d" % i, worker=w)
               for i, w in enumerate([5, 90, 90, 10, 70, 30, 1])]
        r = self.rows(*evs)
        self.assertEqual([(a["identifier"], a["worker_us"]) for a in r["longest_actions"]],
                         [("f1", 90), ("f2", 90), ("f4", 70), ("f5", 30), ("f3", 10)])
        self.assertEqual((r["remote_worker_us_sum"], r["remote_worker_us_max"]), (296, 90))
        self.assertEqual((r["remote_queue_us_sum"], r["remote_queue_us_max"]), (49, 7))
        self.assertEqual((r["remote_wall_us_sum"], r["remote_wall_us_max"]), (1400, 200))

    def test_failed_test_run_and_reupload(self):
        run = span_end({"TestRun": {"suite": {"suite_name": "s", "target_label": {"label": {"package": "p", "name": "s"}}},
                                    "command_report": {"details": {"signed_exit_code": 1, "command_kind": {
                                        "command": {"RemoteCommand": {"cache_hit": False}}},
                                        "metadata": {"execution_time_us": 40}}}}})
        up = span_end({"ReUpload": {"digests_uploaded": 3, "bytes_uploaded": 77}})
        r = self.rows(run, up, up)
        self.assertEqual((r["test_runs"], r["failed_actions"], r["executed_remote"]), (1, 1, 1))
        self.assertEqual((r["reupload_bytes"], r["reupload_digests"]), (154, 6))

    def test_args_redacted_to_200_chars(self):
        head = dict(HEADER, command_line_args=["/bin/buck2", "build", "x" * 500])
        r = self.rows(header=head)
        self.assertEqual(len(r["args"]), 200)
        self.assertTrue(r["args"].endswith("..."))
        r = self.rows(header=dict(HEADER, command_line_args=["/b", "b", "y" * 195]))
        self.assertEqual(r["args"], "b " + "y" * 195)

    def test_single_snapshot_gives_no_byte_delta(self):
        r = self.rows(snapshot(5, 6, 7))
        self.assertIsNone(r["cas_downloaded_bytes"])
        self.assertIsNone(r["cas_uploaded_bytes"])
        self.assertIsNone(r["re_action_cache_lookups"])

    def test_no_exit_code_without_command_report(self):
        self.assertIsNone(self.rows()["exit_code"])


class Discovery(unittest.TestCase):
    def test_since_filter_and_order(self):
        root = project_with(HIT_LOG, TEST_LOG, FAIL_LOG)
        try:
            rows = stats.collect(root)
            self.assertEqual([r["log"] for r in rows], [TEST_LOG, HIT_LOG, FAIL_LOG])
            later = stats.collect(root, since=1793974390.0)
            self.assertEqual([r["log"] for r in later], [HIT_LOG, FAIL_LOG])
            self.assertEqual(stats.collect(root, since=1.8e9), [])
        finally:
            shutil.rmtree(root)

    def test_other_isolation_dirs_are_read(self):
        root = project_with(TEST_LOG)
        try:
            shutil.copytree(Path(root, "buck-out", "v2", "log"), Path(root, "buck-out", "other", "log"))
            self.assertEqual(len(stats.collect(root)), 2)
        finally:
            shutil.rmtree(root)

    def test_pb_zst_goes_through_the_client(self):
        root = project_with()
        try:
            logdir = Path(root, "buck-out", "v2", "log")
            name = "20261106-000000_build_abc_events.pb.zst"
            (logdir / name).write_bytes(b"not read by python")
            fake = Path(root, "fake-buck2")
            fake.write_text("#!/bin/sh\n[ \"$1 $2\" = 'log show' ] || exit 9\ncat '%s'\n" % (FIX / TEST_LOG))
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            rows = stats.collect(root, buck2=str(fake))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["actions_total"], 7)
            self.assertEqual(rows[0]["log"], name)
        finally:
            shutil.rmtree(root)

    def test_undecodable_log_is_an_error_row(self):
        root = project_with()
        try:
            logdir = Path(root, "buck-out", "v2", "log")
            (logdir / "20261106-000000_build_abc_events.pb.zst").write_bytes(b"x")
            fake = Path(root, "bad-buck2")
            fake.write_text("#!/bin/sh\necho boom >&2\nexit 2\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            rows = stats.collect(root, buck2=str(fake))
            self.assertEqual(len(rows), 1)
            self.assertIn("boom", rows[0]["error"])
        finally:
            shutil.rmtree(root)


class Cli(unittest.TestCase):
    def run_cli(self, root, *extra):
        return subprocess.run([sys.executable, "-I", str(TOOL), root, *extra], capture_output=True, text=True)

    def test_json_lines_and_table(self):
        root = project_with(TEST_LOG, FAIL_LOG)
        try:
            out = self.run_cli(root, "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            rows = [json.loads(line) for line in out.stdout.splitlines()]
            self.assertEqual([r["exit_code"] for r in rows], [0, 3])
            table = self.run_cli(root)
            self.assertIn("exit=3", table.stdout)
            self.assertIn("build //selftest/scratch/bad:bad", table.stdout)
            since = self.run_cli(root, "--json", "--since", "1793974460")
            self.assertEqual(len(since.stdout.splitlines()), 1)
        finally:
            shutil.rmtree(root)

    def test_render_error_row(self):
        self.assertEqual(stats.render({"log": "l", "error": "e"}), "l  ERROR e")

    def test_empty_project(self):
        root = tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/var/tmp"))
        try:
            out = self.run_cli(root, "--json")
            self.assertEqual((out.returncode, out.stdout), (0, ""))
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
