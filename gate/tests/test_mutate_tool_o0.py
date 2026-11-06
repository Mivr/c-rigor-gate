"""`tool.py collect` and the -O0 cross-check of equivalent mutants (T051, B15)."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("mutate_tool_o0", HERE.parent.parent / "mutate" / "tool.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

H = ["%064x" % n for n in range(1, 8)]


class CollectTest(unittest.TestCase):
    def test_o0_results_reach_the_report_only_for_the_mutants_that_have_them(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)

            def put(name, obj):
                tool.write_json(tmp / name, obj)
                return str(tmp / name)

            gen = put("gen.json", {"file": "m/a.c", "sha256": "0" * 64, "definitions": 1, "functions": [],
                                   "skipped": [], "hidden": [],
                                   "mutants": [{"id": "a" * 16}, {"id": "b" * 16}]})
            manifest = put("manifest.json", {
                "label": "//m:x", "tests": ["t"], "baseline_runs": {},
                "sources": [{"rel": "m/a.c", "gen": gen, "baseline": put("base.json", {"status": "ok", "hash": H[0]}),
                             "baseline_o0": put("base0.json", {"status": "ok", "hash": H[1]}),
                             "original": put("orig.json", {"status": "ok", "hash": H[0]})}],
                "mutants": {"m/a.c": {
                    "a" * 16: {"info": put("a.json", {"status": "ok", "hash": H[0]}), "runs": {},
                               "o0": put("a0.json", {"status": "ok", "hash": H[2], "detail": "dropped"})},
                    "b" * 16: {"info": put("b.json", {"status": "ok", "hash": H[3]}), "runs": {}},
                }}})
            tool.cmd_collect(["--manifest", manifest, "--out", str(tmp / "report.json")])
            report = json.loads((tmp / "report.json").read_text())
        self.assertEqual(report["sources"][0]["baseline_o0"], {"status": "ok", "hash": H[1]})
        first, second = report["mutants"]
        self.assertEqual(first["compile"]["o0"], {"status": "ok", "hash": H[2]})
        self.assertNotIn("o0", second["compile"])


if __name__ == "__main__":
    unittest.main()
