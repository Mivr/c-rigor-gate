"""The oracle bundle, the `vm-trace/1` reader and the judge `rigor oracle` (T2G7): every tampered bundle is exit 2, the fixture
replays with zero divergence, and a one-byte change in a trace is `oracle-divergence` at the right line and byte."""

import hashlib
import importlib.util
import json
import os
import shutil
import unittest

from rigor_lib import oracle_bundle as ob
from rigor_lib import oracle_judge as oj
from rigor_lib.errors import InternalError
from tests.helpers import GATE_DIR, TempDirTestCase, run_rigor

GENERATOR = GATE_DIR.parent / "selftest" / "sim" / "oracle" / "gen_traces.py"
_spec = importlib.util.spec_from_file_location("oracle_gen_traces", GENERATOR)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)
IDS = ["random-0011", "random-0012", "scripted-01", "scripted-02"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Case(TempDirTestCase):
    def bundle(self, name="bundle"):
        directory = self.tmp / name
        gen.main(str(directory))
        return directory

    def results(self, bundle, name="results"):
        """A replayer that is the Rust model: the output of every trace is the trace itself."""
        directory = self.tmp / name
        shutil.copytree(bundle / "files", directory)
        return directory

    def load_fails(self, directory, needle=None):
        with self.assertRaises(InternalError) as caught:
            ob.load(str(directory))
        if needle is not None:
            self.assertIn(needle, str(caught.exception))


class BundleGreen(Case):
    def test_the_fixture_loads_and_digests_independently_of_its_place(self):
        one, two = self.bundle("one"), self.bundle("two")
        loaded = ob.load(str(one))
        self.assertEqual((loaded.product, loaded.ids), ("canary", tuple(IDS)))
        self.assertEqual(len(loaded.traces["scripted-01"].steps), 9)
        self.assertEqual(ob.digest(loaded), ob.digest(ob.load(str(two))))
        self.assertEqual(ob.digest_entries(loaded)[0], ["oracle.toml", loaded.manifest_sha256])
        self.assertEqual(ob.digest_entries(loaded)[1][0], "files/random-0011.trace")

    def test_the_digest_follows_every_byte(self):
        one = self.bundle("one")
        first = ob.digest(ob.load(str(one)))
        path = one / "oracle.toml"
        path.write_text(path.read_text().replace("T2G7-fixture", "T2G7-other"))
        self.assertNotEqual(ob.digest(ob.load(str(one))), first)

    def test_check_names_the_product(self):
        loaded = ob.load(str(self.bundle()))
        ob.check(loaded, "canary")
        with self.assertRaises(InternalError):
            ob.check(loaded, "other")


class BundleTampered(Case):
    """Every defect of the bundle is exit 2."""

    def test_the_directory(self):
        self.load_fails(self.tmp / "missing")
        plain = self.tmp / "plain"
        plain.write_text("x")
        self.load_fails(plain)
        real = self.bundle("real")
        link = self.tmp / "link"
        os.symlink(real, link)
        self.load_fails(link, "symlink")

    def test_the_top_level_entries(self):
        base = self.bundle()
        (base / "extra").write_text("x")
        self.load_fails(base, "exactly")
        base = self.bundle("b2")
        (base / "oracle.toml").unlink()
        self.load_fails(base, "exactly")

    def test_files_must_be_a_directory(self):
        base = self.bundle()
        shutil.rmtree(base / "files")
        (base / "files").write_text("x")
        self.load_fails(base, "not a directory")

    def test_symlinks_and_special_files(self):
        base = self.bundle()
        victim = base / "files" / "scripted-01.trace"
        data = victim.read_bytes()
        victim.unlink()
        (self.tmp / "elsewhere").write_bytes(data)
        os.symlink(self.tmp / "elsewhere", victim)
        self.load_fails(base)
        base = self.bundle("fifo")
        victim = base / "files" / "scripted-01.trace"
        victim.unlink()
        os.mkfifo(victim)
        self.load_fails(base)
        base = self.bundle("manifest-link")
        (base / "oracle.toml").rename(self.tmp / "m.toml")
        os.symlink(self.tmp / "m.toml", base / "oracle.toml")
        self.load_fails(base)

    def test_an_unlisted_and_a_missing_file(self):
        base = self.bundle()
        (base / "files" / "extra.trace").write_bytes((base / "files" / "scripted-01.trace").read_bytes())
        self.load_fails(base, "differ")
        base = self.bundle("b2")
        (base / "files" / "scripted-01.trace").unlink()
        self.load_fails(base, "differ")
        base = self.bundle("b3")
        (base / "files" / "sub").mkdir()
        self.load_fails(base, "differ")

    def test_a_changed_byte_fails_the_listed_hash(self):
        base = self.bundle()
        path = base / "files" / "scripted-01.trace"
        path.write_bytes(path.read_bytes().replace(b'"entered":1', b'"entered":2', 1))
        self.load_fails(base, "sha256")

    def edit(self, base, old, new, count=1):
        path = base / "oracle.toml"
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, count))

    def test_the_manifest(self):
        for old, new, name in (
                ("product = ", "producer = ", "top key"),
                ('origin = "T2G7-fixture"\n', "", "no origin"),
                ('produced_from = "' + "0" * 40 + '"', 'produced_from = "ABC"', "bad sha1"),
                ('product = "canary"', 'product = ""', "empty product"),
                ("steps = 9", "steps = 8", "steps"),
                ("steps = 9", 'steps = "9"', "steps type"),
                ("steps = 9", "steps = -1", "steps negative"),
                ("steps = 9", "steps = 9\nextra = 1", "extra trace key"),
                ('[trace."scripted-01"]', '[trace."bad id"]', "bad id"),
        ):
            with self.subTest(name):
                base = self.bundle("m-" + name.replace(" ", "-"))
                self.edit(base, old, new)
                self.load_fails(base)
        base = self.bundle("garbled")
        (base / "oracle.toml").write_bytes(b"\xff\xfe not toml")
        self.load_fails(base, "TOML")

    def test_a_manifest_without_traces(self):
        base = self.bundle()
        (base / "oracle.toml").write_text('product = "canary"\norigin = "x"\nproduced_from = "%s"\ntrace = {}\n' % ("0" * 40))
        self.load_fails(base, "at least one")

    def test_a_sha_that_is_not_hex(self):
        base = self.bundle()
        text = (base / "oracle.toml").read_text()
        value = ob.load(str(base)).file_sha256["scripted-01"]
        (base / "oracle.toml").write_text(text.replace(value, value.upper()))
        self.load_fails(base, "64 lowercase hex")


class TraceReader(Case):
    GOOD = (b'{"k":"cfg","v":"vm-trace/1","id":"x","src":"' + b"0" * 40 + b'","seed":1,"start_ms":0,"lang":"bg",'
            b'"inventory":{"sizes":[],"lockers":[]},"codes":[],"pulse_units":5,"min_free_mb":10,"offline_age_ms":null}\n')

    def parse(self, body, allow_ns=False):
        return ob.parse_trace("t", self.GOOD + body, allow_ns)

    def bad(self, body, needle=None, allow_ns=False, whole=None):
        with self.assertRaises(InternalError) as caught:
            ob.parse_trace("t", whole if whole is not None else self.GOOD + body, allow_ns)
        if needle:
            self.assertIn(needle, str(caught.exception))

    def test_a_good_trace_with_its_positions(self):
        trace = self.parse(b'{"k":"in","t":5,"op":"digit","d":3}\n{"k":"fx","t":5,"port":"codes.role_of"}\n'
                           b'{"k":"vw","t":5,"s":{"screen":"pad"}}\n')
        self.assertEqual(len(trace.steps), 1)
        step = trace.steps[0]
        self.assertEqual((trace.cfg.line, step.input.line, step.fx[0].line, step.view.line), (1, 2, 3, 4))
        self.assertEqual(step.state, b'{"screen":"pad"}')
        self.assertEqual(trace.sha256, sha(self.GOOD + b'{"k":"in","t":5,"op":"digit","d":3}\n{"k":"fx","t":5,"port":"codes.role_of"}\n'
                                           b'{"k":"vw","t":5,"s":{"screen":"pad"}}\n'))

    def test_every_op_has_its_keys(self):
        for op, extra in ob.OPS.items():
            line = '{"k":"in","t":0,"op":"%s"%s}\n' % (op, "".join(',"%s":1' % key for key in extra))
            self.parse(line.encode() + b'{"k":"vw","t":0,"s":{}}\n')
            self.bad(line.replace("}\n", ',"more":1}\n').encode() + b'{"k":"vw","t":0,"s":{}}\n', "input record")

    def test_defects(self):
        vw = b'{"k":"vw","t":0,"s":{}}\n'
        entry = b'{"k":"in","t":0,"op":"cancel"}\n'
        self.bad(b"", None, whole=b"")
        self.bad(b"", "LF", whole=self.GOOD[:-1])
        self.bad(b"", "CR", whole=self.GOOD.replace(b"\n", b"\r\n"))
        self.bad(entry + b"\n" + vw, "empty line")
        self.bad(entry, "no view")
        self.bad(entry + vw.replace(b"0", b"1"), "at the time")
        self.bad(entry + b'{"k":"vw","t":0,"s":[]}\n', "not a vw")
        self.bad(entry + b'{"k":"vw","t":0,"s":{x}}\n', "JSON")
        self.bad(entry + b'{"k":"vw","t":00,"s":{}}\n', "at the time")
        self.bad(b'{"k":"in","t":0,"op":"nope"}\n' + vw, "input record")
        self.bad(b'{"k":"in","op":"cancel","t":0}\n' + vw, "keys")
        self.bad(b'{"k":"in", "t":0,"op":"cancel"}\n' + vw, "compact")
        self.bad(b'{"k":"in","t":-1,"op":"cancel"}\n' + vw.replace(b'"t":0', b'"t":-1'), None)
        self.bad(entry + b'{"k":"fx","t":1,"port":"codes.role_of"}\n' + vw, "fx record")
        self.bad(entry + b'{"k":"fx","t":0,"port":"relay.on"}\n' + vw, "fx record")
        self.bad(vw + entry, "must start")
        self.bad(b'x', None, whole=self.GOOD.replace(b'"v":"vm-trace/1"', b'"v":"vm-trace/2"') + entry + vw)
        self.bad(b'', "keys", whole=self.GOOD.replace(b'"v":"vm-trace/1","id":"x"', b'"id":"x","v":"vm-trace/1"') + entry + vw)
        self.bad(b'', None, whole=b"[1]\n" + entry + vw)
        self.bad(b'', "keys must be", whole=entry + vw)

    def test_ns_is_replayer_output_only(self):
        entry = b'{"k":"in","t":0,"op":"cancel"}\n'
        self.bad(entry + b'{"k":"ns","t":0}\n', "vw record")
        trace = self.parse(entry + b'{"k":"ns","t":0}\n', allow_ns=True)
        self.assertFalse(trace.steps[0].settled)
        self.bad(entry + b'{"k":"ns","t":0}\n' + entry + b'{"k":"vw","t":0,"s":{}}\n', "after the ns", allow_ns=True)

    def test_the_view_text_is_kept_as_written(self):
        weird = b'{"k":"in","t":0,"op":"cancel"}\n{"k":"vw","t":0,"s":{"a" : 1,"b":"\\u00e9"}}\n'
        self.assertEqual(self.parse(weird).steps[0].state, b'{"a" : 1,"b":"\\u00e9"}')


class FirstDiff(unittest.TestCase):
    def test_positions(self):
        diff = oj.trace_first_diff
        self.assertIsNone(diff(b"", b""))
        self.assertIsNone(diff(b"a\nb", b"a\nb"))
        self.assertEqual(diff(b"abc", b"abd"), (1, 2))
        self.assertEqual(diff(b"a\nbcd\ne", b"a\nbxd\ne"), (2, 1))
        self.assertEqual(diff(b"a\nb", b"a\nbc"), (2, 1))
        self.assertEqual(diff(b"a\nb", b"a\nb\nc"), (3, 0))
        self.assertEqual(diff(b"a\nb\nc", b"a\nb"), (3, 0))
        self.assertEqual(diff(b"a\n", b"a"), (2, 0))
        self.assertEqual(diff(b"\xc3\xa9x", b"\xc3\xa9y"), (1, 2))


def toml_file(directory, name, text):
    path = directory / name
    path.write_text(text)
    return str(path)


class Tables(Case):
    def test_defaults_are_empty(self):
        self.assertEqual(oj.load_table(None), oj.Table())
        self.assertEqual(oj.load_excluded(None).entries, {})
        self.assertEqual(oj.load_policy(None), oj.OraclePolicy())

    def test_a_policy(self):
        text = 'required = true\nreplayer = "//a:b"\ntraces = ["x", "y"]\nexcluded_max = 2\n'
        policy = oj.load_policy(toml_file(self.tmp, "p.toml", text))
        self.assertEqual((policy.present, policy.required, policy.replayer, policy.traces, policy.excluded_max),
                         (True, True, "//a:b", ("x", "y"), 2))

    def test_bad_policies_are_exit_2(self):
        for text in ('required = 1', 'replayer = "a:b"', 'traces = ["x", "x"]', 'traces = ["a b"]', 'excluded_max = -1',
                     'excluded_max = true', 'other = 1', 'traces = "x"', "not toml ["):
            with self.subTest(text), self.assertRaises(InternalError):
                oj.load_policy(toml_file(self.tmp, "p.toml", text))

    def test_a_table_with_rows(self):
        text = ('[[row]]\nid = "N1"\nkind = "drop-field"\nfield = "at"\ndecision = "D1"\nreason = "r"\n'
                '[[row]]\nid = "N2"\nkind = "round-field"\nfield = "countdown_ms"\nto = 250\ndecision = "D2"\nreason = "r"\n'
                '[[row]]\nid = "N3"\nkind = "drop-fx"\nport = "sync.note"\ndecision = "D3"\nreason = "r"\n')
        table = oj.load_table(toml_file(self.tmp, "n.toml", text))
        self.assertEqual([r.id for r in table.rows], ["N1", "N2", "N3"])
        self.assertEqual(table.sha256, sha(text.encode()))
        self.assertEqual(table.dropped_ports, {"sync.note"})

    def test_bad_tables_are_exit_2(self):
        row = '[[row]]\nid = "N1"\nkind = "drop-field"\nfield = "at"\ndecision = "D1"\nreason = "r"\n'
        for text in (row.replace('decision = "D1"\n', ""), row.replace('reason = "r"', 'reason = ""'),
                     row.replace("drop-field", "magic"), row + 'to = 2\n', row.replace('field = "at"', 'port = "sync.note"'),
                     row + row.replace("N1", "N2"), row + row, 'x = 1', row.replace('"at"', '""'),
                     '[[row]]\nid = "N1"\nkind = "round-field"\nfield = "a"\nto = 1\ndecision = "D"\nreason = "r"\n',
                     '[[row]]\nid = "N1"\nkind = "drop-fx"\nport = "relay.on"\ndecision = "D"\nreason = "r"\n',
                     '[[row]]\nid = "N 1"\nkind = "drop-field"\nfield = "a"\ndecision = "D"\nreason = "r"\n'):
            with self.subTest(text), self.assertRaises(InternalError):
                oj.load_table(toml_file(self.tmp, "n.toml", text))

    def test_exclusions(self):
        row = '[[exclude]]\ntrace_id = "x"\nreason = "r"\ndecision = "D1"\n'
        excluded = oj.load_excluded(toml_file(self.tmp, "e.toml", row))
        self.assertEqual(excluded.entries, {"x": ("r", "D1")})
        for text in (row + row, row.replace('decision = "D1"\n', ""), row + "extra = 1\n", 'x = 1',
                     row.replace('"x"', '"a b"'), row.replace('"r"', '""')):
            with self.subTest(text), self.assertRaises(InternalError):
                oj.load_excluded(toml_file(self.tmp, "e.toml", text))

    def test_normalisation_rows(self):
        table = oj.Table((oj.Row("N1", "drop-field", "D", "r", field="at"),
                          oj.Row("N2", "round-field", "D", "r", field="countdown_ms", to=250)))
        text = b'{"screen":"x","at":5,"countdown_ms":1,"in":{"countdown_ms":251,"at":1},"l":[{"countdown_ms":500}]}'
        self.assertEqual(oj.normalise(table, text),
                         b'{"screen":"x","countdown_ms":250,"in":{"countdown_ms":500},"l":[{"countdown_ms":500}]}')
        self.assertEqual(oj.normalise(oj.Table(), text), text)
        self.assertEqual(oj.normalise(table, b'{"countdown_ms":"s"}'), b'{"countdown_ms":"s"}')


class Judge(Case):
    def run_judge(self, bundle, results, policy="", normalise="", excluded=""):
        loaded = ob.load(str(bundle))
        files = {"policy": policy, "normalise": normalise, "excluded": excluded}
        paths = {name: (toml_file(self.tmp, name + ".toml", text) if text else None) for name, text in files.items()}
        table, skipped = oj.load_table(paths["normalise"]), oj.load_excluded(paths["excluded"])
        found = oj.judge(oj.load_policy(paths["policy"]), loaded, table, skipped, oj.load_results(str(results), loaded, skipped))
        return [(item["rule"], {k: v for k, v in item.items() if k not in ("rule", "severity")}) for item in found]

    def test_the_fixture_replays_with_zero_divergence(self):
        base = self.bundle()
        self.assertEqual(self.run_judge(base, self.results(base)), [])

    def test_one_changed_byte_is_a_divergence_at_its_line_and_byte(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        lines = path.read_bytes().split(b"\n")
        target = lines[14]   # line 15: the view after the first tick
        self.assertIn(b'"countdown_ms":2000', target)
        offset = target.index(b"2000")
        lines[14] = target[:offset] + b"3" + target[offset + 1:]
        path.write_bytes(b"\n".join(lines))
        found = self.run_judge(base, results)
        self.assertEqual(found, [("oracle-divergence", {"trace": "scripted-01", "step": 5, "line": 15, "byte": offset, "what": "vw"})])

    def test_a_changed_fx_is_reported_as_fx(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        path.write_bytes(path.read_bytes().replace(b'"open","row":1,"col":2'.replace(b'"open"', b'"opener.open"'), b'"opener.open","row":1,"col":3'))
        found = self.run_judge(base, results)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0][0], found[0][1]["what"], found[0][1]["line"], found[0][1]["step"]), ("oracle-divergence", "fx", 12, 4))

    def test_a_missing_fx_and_an_extra_fx(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        lines = path.read_bytes().split(b"\n")
        del lines[10]
        path.write_bytes(b"\n".join(lines))
        found = self.run_judge(base, results)
        self.assertEqual((found[0][1]["line"], found[0][1]["what"]), (11, "fx"))

    def test_a_changed_input_and_a_changed_cfg(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-02.trace"
        path.write_bytes(path.read_bytes().replace(b'"d":5', b'"d":6', 1))
        self.assertEqual(self.run_judge(base, results)[0][1]["what"], "in")
        results = self.results(base, "r2")
        path = results / "scripted-02.trace"
        path.write_bytes(path.read_bytes().replace(b'"seed":2', b'"seed":3', 1))
        found = self.run_judge(base, results)
        self.assertEqual((found[0][1]["step"], found[0][1]["line"], found[0][1]["what"]), (0, 1, "cfg"))

    def test_fewer_and_more_steps(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        lines = path.read_bytes().split(b"\n")
        path.write_bytes(b"\n".join(lines[:-3]) + b"\n")   # drops the last step (in, vw)
        found = self.run_judge(base, results)
        self.assertEqual((found[0][1]["step"], found[0][1]["line"], found[0][1]["what"]), (8, 21, "steps"))
        results = self.results(base, "r2")
        path = results / "scripted-01.trace"
        text = path.read_bytes()
        path.write_bytes(text + b'{"k":"in","t":3000,"op":"cancel"}\n{"k":"vw","t":3000,"s":{}}\n')
        found = self.run_judge(base, results)
        self.assertEqual((found[0][1]["step"], found[0][1]["line"], found[0][1]["what"]), (9, 23, "steps"))

    def test_a_step_that_does_not_settle(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        lines = path.read_bytes().split(b"\n")
        lines[2:] = [lines[1], b'{"k":"ns","t":0}', b""]
        lines[2:] = [b'{"k":"ns","t":0}', b""]
        path.write_bytes(b"\n".join(lines))
        self.assertEqual(self.run_judge(base, results), [("oracle-no-settle", {"trace": "scripted-01", "step": 0})])

    def test_the_count_is_checked(self):
        base = self.bundle()
        results = self.results(base)
        (results / "scripted-01.trace").unlink()
        self.assertEqual(self.run_judge(base, results), [("oracle-count-short", {"expected": 4, "replayed": 3})])

    def test_strangers_in_the_results_are_exit_2(self):
        base = self.bundle()
        for name in ("stray.trace", "scripted-01.report", "README"):
            results = self.results(base, "r-" + name)
            (results / name).write_bytes((results / "scripted-01.trace").read_bytes())
            with self.subTest(name), self.assertRaises(InternalError):
                self.run_judge(base, results)
        results = self.results(base, "r-bad")
        (results / "scripted-01.trace").write_bytes(b"garbage\n")
        with self.assertRaises(InternalError):
            self.run_judge(base, results)
        with self.assertRaises(InternalError):
            self.run_judge(base, self.tmp / "no-such-directory")

    def test_policy_traces_the_bundle_lacks(self):
        base = self.bundle()
        found = self.run_judge(base, self.results(base), policy='traces = ["scripted-01", "scripted-99"]\n')
        self.assertEqual(found, [("oracle-bundle-missing", {"trace": "scripted-99"})])

    def test_no_bundle_while_required(self):
        policy = oj.load_policy(toml_file(self.tmp, "p.toml", "required = true\n"))
        found = oj.judge(policy, None, oj.Table(), oj.Excluded(), {})
        self.assertEqual([item["rule"] for item in found], ["oracle-bundle-missing"])
        self.assertEqual(oj.judge(oj.OraclePolicy(), None, oj.Table(), oj.Excluded(), {}), [])

    def test_exclusions_are_a_ratchet(self):
        base = self.bundle()
        results = self.results(base)
        (results / "scripted-01.trace").unlink()
        row = '[[exclude]]\ntrace_id = "scripted-01"\nreason = "r"\ndecision = "D1"\n'
        found = self.run_judge(base, results, excluded=row)
        self.assertEqual(found, [("oracle-excluded-grew", {"excluded": 1, "max": 0})])
        self.assertEqual(self.run_judge(base, results, excluded=row, policy="excluded_max = 1\n"), [])
        # An excluded trace that was replayed anyway, or one the bundle does not hold, is exit 2.
        with self.assertRaises(InternalError):
            self.run_judge(base, self.results(base, "r2"), excluded=row, policy="excluded_max = 1\n")
        with self.assertRaises(InternalError):
            self.run_judge(base, results, excluded=row.replace("scripted-01", "ghost"), policy="excluded_max = 1\n")

    def test_the_table_makes_two_texts_equal_and_only_then(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        original = path.read_bytes()
        path.write_bytes(original.replace(b'"countdown_ms":2000', b'"countdown_ms":1999'))
        self.assertEqual(self.run_judge(base, results)[0][0], "oracle-divergence")
        rows = '[[row]]\nid = "N1"\nkind = "round-field"\nfield = "countdown_ms"\nto = 250\ndecision = "D1"\nreason = "r"\n'
        self.assertEqual(self.run_judge(base, results, normalise=rows), [])
        path.write_bytes(original.replace(b'"countdown_ms":2000', b'"countdown_ms":2600'))
        self.assertEqual(self.run_judge(base, results, normalise=rows)[0][0], "oracle-divergence")

    def test_dropped_fx_ports_and_fields(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        path.write_bytes(path.read_bytes().replace(b'{"k":"fx","t":3000,"port":"audit.append","kind":"closed"}\n', b""))
        self.assertEqual(self.run_judge(base, results)[0][0], "oracle-divergence")
        rows = '[[row]]\nid = "N1"\nkind = "drop-fx"\nport = "audit.append"\ndecision = "D1"\nreason = "r"\n'
        self.assertEqual(self.run_judge(base, results, normalise=rows), [])

    def test_findings_carry_no_trace_text(self):
        base = self.bundle()
        results = self.results(base)
        path = results / "scripted-01.trace"
        path.write_bytes(path.read_bytes().replace(b'"entered":1', b'"entered":7', 1))
        text = json.dumps(self.run_judge(base, results))
        for word in ("entered", "screen", "countdown", "1234"):
            self.assertNotIn(word, text)


class Command(Case):
    def test_the_command_passes_and_fails(self):
        base = self.bundle()
        results = self.results(base)
        out = self.tmp / "out.json"
        argv = ["oracle", "--bundle", base, "--results", results, "--out", out]
        outcome = run_rigor(argv)
        self.assertEqual(outcome.code, 0, outcome.stderr)
        document = json.loads(out.read_text())
        self.assertEqual((document["status"], document["findings"]), ("PASS", []))
        self.assertEqual(document["metadata"]["traces"], 4)
        self.assertEqual(document["metadata"]["oracle_sha256"], ob.digest(ob.load(str(base))))
        path = results / "scripted-02.trace"
        path.write_bytes(path.read_bytes().replace(b'"entered":2', b'"entered":3', 1))
        outcome = run_rigor(argv)
        self.assertEqual(outcome.code, 1, outcome.stderr)
        self.assertEqual([f["rule"] for f in json.loads(out.read_text())["findings"]], ["oracle-divergence"])

    def test_a_tampered_bundle_is_exit_2_and_leaves_no_pass(self):
        base = self.bundle()
        results = self.results(base)
        (base / "files" / "scripted-01.trace").write_bytes(b"x\n")
        out = self.tmp / "out.json"
        outcome = run_rigor(["oracle", "--bundle", base, "--results", results, "--out", out])
        self.assertEqual(outcome.code, 2)
        self.assertEqual(json.loads(out.read_text())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
