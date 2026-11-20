"""`rigor oracle`: the verdict on the byte-identical replay of the hidden Rust traces (T2G7, P330 §3.3 and §3.4; docs/oracle.md).
Run by `rigor grade` as the gate `oracle` (grade_oracle.py).

    rigor oracle --bundle DIR --results DIR --policy P.toml [--normalise N.toml] [--excluded E.toml] [--out F]

`--bundle` is the oracle bundle (oracle_bundle.py, the hidden half). `--results` is a flat directory with one `<trace id>.trace`
per trace the replayer ran: the output of the product's replayer, in the same `vm-trace/1` format as the input (`ns` records
allowed). The judge trusts nothing the replayer says about itself: it parses the output, compares it with the Rust trace step by
step and computes the first difference itself. Per trace and step, after the normalisation table:

1. the `in` line (the replayer must replay the input it was given) and the `cfg` line are byte-identical;
2. the ordered `fx` lines are equal, and so is the number of steps;
3. the `vw` text `s` is byte-identical (`trace_first_diff`; no JSON-level tolerance).

Findings (errors; docs/oracle.md): `oracle-divergence` (trace, step, line, byte, what), `oracle-no-settle` (trace, step),
`oracle-bundle-missing` (a trace id of the policy that the bundle lacks, or no bundle at all while the policy requires one),
`oracle-count-short` (fewer traces replayed than the bundle holds, without the excluded ones), `oracle-excluded-grew` (more
exclusions than the policy's `excluded_max`). Findings carry ids and positions only, never trace text. Every malformed input is exit 2.

The policy (`products/<p>/oracle-policy.toml`), the normalisation table (`oracle-normalise.toml`, empty by default) and the exclusions
(`oracle-excluded.toml`, a ratchet) are gate files; docs/oracle.md has their keys.
"""

import json
import os
import re
import tomllib
from dataclasses import dataclass, field

from rigor_lib import facts_data, jsonio, oracle_bundle
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "oracle"
SUFFIX = oracle_bundle.SUFFIX
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_ROW_KEYS = {"id", "kind", "decision", "reason"}
_KIND_KEYS = {"drop-field": {"field"}, "round-field": {"field", "to"}, "drop-fx": {"port"}}
_BIG = 1 << 31


def _fail(where, why):
    raise InternalError("oracle: %s: %s" % (where, why))


# ------------------------------------------------------------------------------------------------ gate files

@dataclass(frozen=True)
class OraclePolicy:
    present: bool = False
    required: bool = False
    replayer: str = ""
    traces: tuple = ()
    excluded_max: int = 0


@dataclass(frozen=True)
class Row:
    id: str
    kind: str
    decision: str
    reason: str
    field: str = ""
    port: str = ""
    to: int = 0


@dataclass(frozen=True)
class Table:
    rows: tuple = ()
    sha256: str = None   # of the file, None without one

    def fields(self, kind):
        return {row.field: row for row in self.rows if row.kind == kind}

    @property
    def dropped_ports(self):
        return {row.port for row in self.rows if row.kind == "drop-fx"}


@dataclass(frozen=True)
class Excluded:
    entries: dict = field(default_factory=dict)   # trace id -> (reason, decision)
    sha256: str = None


def _toml(path, what):
    data = jsonio.read_bytes(path)
    try:
        return tomllib.loads(data.decode("utf-8")), jsonio.sha256_hex(data)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (what, exc)) from exc


def _text(where, value):
    if not isinstance(value, str) or value == "":
        _fail(where, "must be a non-empty string")
    return value


def load_policy(path):
    """The OraclePolicy of `oracle-policy.toml`; the defaults of "no oracle" without the file.

        required = true                          # the product must be graded with --oracle (`oracle-bundle-missing`)
        replayer = "//apps/lockers/lkapp/sim:oracle_replay"    # the c_binary that replays a trace (stdin -> stdout)
        traces = ["scripted-01", ...]            # trace ids the bundle must hold (`oracle-bundle-missing`)
        excluded_max = 0                         # the ratchet: at most this many entries in oracle-excluded.toml
    """
    if path is None:
        return OraclePolicy()
    document, _ = _toml(path, path)
    if not set(document) <= {"required", "replayer", "traces", "excluded_max"}:
        _fail("policy", "may only contain required, replayer, traces and excluded_max")
    required = document.get("required", False)
    if type(required) is not bool:
        _fail("policy required", "must be true or false")
    replayer = document.get("replayer", "")
    if not isinstance(replayer, str) or (replayer != "" and not facts_data.LABEL.fullmatch(replayer)):
        _fail("policy replayer", "must be a target label")
    traces = document.get("traces", [])
    if not isinstance(traces, list) or not all(isinstance(t, str) and oracle_bundle.TRACE_ID.fullmatch(t) for t in traces) \
            or len(set(traces)) != len(traces):
        _fail("policy traces", "must be a list of distinct trace ids")
    ceiling = document.get("excluded_max", 0)
    if type(ceiling) is not int or not 0 <= ceiling <= _BIG:
        _fail("policy excluded_max", "must be a non-negative integer")
    return OraclePolicy(True, required, replayer, tuple(traces), ceiling)


def _row(index, raw):
    where = "normalise row %d" % index
    if not isinstance(raw, dict) or raw.get("kind") not in _KIND_KEYS or set(raw) != _ROW_KEYS | _KIND_KEYS[raw["kind"]]:
        _fail(where, "needs exactly id, kind (%s), decision, reason and the keys of its kind" % ", ".join(sorted(_KIND_KEYS)))
    for key in ("id", "decision", "reason"):
        _text("%s %s" % (where, key), raw[key])
    if not _NAME.fullmatch(raw["id"]) or not _NAME.fullmatch(raw["decision"]):
        _fail(where, "odd id or decision")
    fields = {}
    if "field" in raw:
        fields["field"] = _text(where + " field", raw["field"])
    if "port" in raw:
        if raw["port"] not in oracle_bundle.PORTS:
            _fail(where, "port must be one of %s" % list(oracle_bundle.PORTS))
        fields["port"] = raw["port"]
    if "to" in raw:
        if type(raw["to"]) is not int or not 2 <= raw["to"] <= _BIG:
            _fail(where, "to must be an integer of at least 2")
        fields["to"] = raw["to"]
    return Row(raw["id"], raw["kind"], raw["decision"], raw["reason"], **fields)


def load_table(path):
    """The normalisation table of `oracle-normalise.toml` (P330 §3.4): `[[row]]` tables, none by default. Every row needs a
    decision id and a reason, and applies to the Rust and the C text alike."""
    if path is None:
        return Table()
    document, sha = _toml(path, path)
    if not set(document) <= {"row"} or not isinstance(document.get("row", []), list):
        _fail("normalise", "may only contain [[row]] tables")
    rows = tuple(_row(index, raw) for index, raw in enumerate(document.get("row", [])))
    if len({row.id for row in rows}) != len(rows):
        _fail("normalise", "row ids must be distinct")
    kinds = [(row.kind, row.field or row.port) for row in rows]
    if len(set(kinds)) != len(kinds):
        _fail("normalise", "two rows for the same field or port")
    return Table(rows, sha)


def load_excluded(path):
    """The exclusions of `oracle-excluded.toml`: `[[exclude]]` tables of `trace_id`, `reason`, `decision`."""
    if path is None:
        return Excluded()
    document, sha = _toml(path, path)
    rows = document.get("exclude", [])
    if not set(document) <= {"exclude"} or not isinstance(rows, list):
        _fail("excluded", "may only contain [[exclude]] tables")
    entries = {}
    for index, raw in enumerate(rows):
        where = "exclude entry %d" % index
        if not isinstance(raw, dict) or set(raw) != {"trace_id", "reason", "decision"}:
            _fail(where, "needs exactly trace_id, reason and decision")
        trace_id = _text(where + " trace_id", raw["trace_id"])
        if not oracle_bundle.TRACE_ID.fullmatch(trace_id) or trace_id in entries:
            _fail(where, "bad or repeated trace id %r" % trace_id)
        _text(where + " reason", raw["reason"])
        if not _NAME.fullmatch(_text(where + " decision", raw["decision"])):
            _fail(where, "odd decision id")
        entries[trace_id] = (raw["reason"], raw["decision"])
    return Excluded(entries, sha)


# ------------------------------------------------------------------------------------------------ comparison

def trace_first_diff(a, b):
    """(line, byte) of the first difference of two byte strings, or None when they are equal. `line` is 1-based, `byte` the
    0-based offset in that line; when one text ends inside the other the position is where the shorter one ends (the line
    after its last line when it ends at a line end). This is the position `oracle-divergence` reports."""
    left, right = a.split(b"\n"), b.split(b"\n")
    for number, (x, y) in enumerate(zip(left, right), 1):
        if x != y:
            size = 0
            while size < min(len(x), len(y)) and x[size] == y[size]:
                size += 1
            return number, size
    if len(left) != len(right):
        return min(len(left), len(right)) + 1, 0
    return None


def _walk(value, change):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in change:
                kept = change[key](item)
                if kept is None:
                    continue
                item = kept[0]
            out[key] = _walk(item, change)
        return out
    if isinstance(value, list):
        return [_walk(item, change) for item in value]
    return value


def _changes(table):
    change = {name: (lambda item: None) for name in table.fields("drop-field")}
    for name, row in table.fields("round-field").items():
        change[name] = (lambda item, to=row.to: ((-(-item // to) * to,) if type(item) is int else (item,)))
    return change


def normalise(table, text):
    """The text of a `vw.s` or `fx` record after the table's field rows; the text itself without rows (never re-serialised)."""
    change = _changes(table)
    if not change:
        return text
    return json.dumps(_walk(json.loads(text.decode("utf-8")), change), separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _step_lines(table, step):
    """The lines of one step as the comparison sees them: the input, the fx (rows applied) and the view (its `s` normalised)."""
    lines = [step.input.text]
    lines += [normalise(table, fx.text) for fx in step.fx
              if json.loads(fx.text.decode("utf-8"))["port"] not in table.dropped_ports]
    if step.settled:
        head = step.view.text[:step.view.text.index(b'"s":') + 4]
        lines.append(head + normalise(table, step.state) + b"}")
    return lines


def compare(table, rust, replay):
    """The first divergence of a replay from its Rust trace, as ("divergence", step, line, byte, what) or ("no-settle", step),
    or None. `line` is the line of the Rust file, `byte` the offset in that line (in the normalised text)."""
    if rust.cfg.text != replay.cfg.text:
        return ("divergence", 0, 1, trace_first_diff(rust.cfg.text, replay.cfg.text)[1], "cfg")
    for index, step in enumerate(rust.steps):
        if index >= len(replay.steps):
            return ("divergence", index, step.input.line, 0, "steps")
        other = replay.steps[index]
        if not other.settled:
            return ("no-settle", index)
        left, right = _step_lines(table, step), _step_lines(table, other)
        diff = trace_first_diff(b"\n".join(left), b"\n".join(right))
        if diff is not None:
            return ("divergence", index, step.input.line + diff[0] - 1, diff[1], _what(left, right, diff[0]))
    if len(replay.steps) > len(rust.steps):
        return ("divergence", len(rust.steps), rust.lines + 1, 0, "steps")
    return None


def _what(left, right, line):
    """Which record the first difference is in: the input, an fx line or the view (the Rust side's, else the replayer's)."""
    own = left if line <= len(left) else right
    text = own[line - 1]
    return "in" if text.startswith(b'{"k":"in"') else "fx" if text.startswith(b'{"k":"fx"') else "vw"


# ------------------------------------------------------------------------------------------------ results

def load_results(directory, bundle, excluded):
    """{trace id: Trace} of the replayer's output; anything that is not `<id>.trace` of the bundle is exit 2."""
    if not os.path.isdir(directory):
        _fail(directory, "the results directory does not exist")
    found = {}
    for name in sorted(os.listdir(directory)):
        trace_id = name[:-len(SUFFIX)] if name.endswith(SUFFIX) else None
        path = os.path.join(directory, name)
        if trace_id not in bundle.traces or trace_id in excluded.entries or os.path.islink(path) or not os.path.isfile(path):
            _fail(path, "not the output of a replayed trace of the bundle")
        found[trace_id] = oracle_bundle.parse_trace(name, jsonio.read_bytes(path), allow_ns=True)
    return found


def policy_findings(policy, bundle, excluded):
    found = []
    if bundle is None:
        return [finding("oracle-bundle-missing", reason="no bundle")] if policy.required else []
    found.extend(finding("oracle-bundle-missing", trace=trace_id) for trace_id in policy.traces if trace_id not in bundle.traces)
    unknown = sorted(set(excluded.entries) - set(bundle.traces))
    if unknown:
        _fail("excluded", "entries for traces the bundle does not hold: %s" % unknown[:3])
    if len(excluded.entries) > policy.excluded_max:
        found.append(finding("oracle-excluded-grew", excluded=len(excluded.entries), max=policy.excluded_max))
    return found


def judge(policy, bundle, table, excluded, results):
    """The findings over the bundle (None without one), the normalisation table, the exclusions and the replayer's results."""
    found = policy_findings(policy, bundle, excluded)
    if bundle is None:
        return found
    due = [trace_id for trace_id in bundle.ids if trace_id not in excluded.entries]
    if len(results) < len(due):
        found.append(finding("oracle-count-short", expected=len(due), replayed=len(results)))
    for trace_id in due:
        outcome = compare(table, bundle.traces[trace_id], results[trace_id]) if trace_id in results else None
        if outcome is None:
            continue
        if outcome[0] == "no-settle":
            found.append(finding("oracle-no-settle", trace=trace_id, step=outcome[1]))
        else:
            found.append(finding("oracle-divergence", trace=trace_id, step=outcome[1], line=outcome[2], byte=outcome[3],
                                 what=outcome[4]))
    return found


def metadata_of(bundle, results, table, excluded):
    if bundle is None:
        return {"traces": 0, "replayed": 0, "excluded": len(excluded.entries), "steps": 0}
    return {"traces": len(bundle.traces), "replayed": len(results), "excluded": len(excluded.entries),
            "steps": sum(len(t.steps) for t in bundle.traces.values()), "oracle_sha256": oracle_bundle.digest(bundle),
            "normalise_rows": [row.id for row in table.rows], "normalise_sha256": table.sha256, "excluded_sha256": excluded.sha256}


def run(args):
    policy = load_policy(args.policy)
    bundle = oracle_bundle.load(args.bundle) if args.bundle is not None else None
    table, excluded = load_table(args.normalise), load_excluded(args.excluded)
    results = load_results(args.results, bundle, excluded) if bundle is not None else {}
    return GateResult(GATE_ID, judge(policy, bundle, table, excluded, results), metadata_of(bundle, results, table, excluded))


def add_parser(subparsers):
    parser = subparsers.add_parser("oracle", allow_abbrev=False,
                                   help="byte-identical replay of the hidden Rust traces: divergence, settling, counts")
    parser.add_argument("--bundle", help="the oracle bundle (oracle.toml + files/); none is a finding if the policy requires one")
    parser.add_argument("--results", required=True)
    parser.add_argument("--policy", help="products/<p>/oracle-policy.toml")
    parser.add_argument("--normalise", help="products/<p>/oracle-normalise.toml")
    parser.add_argument("--excluded", help="products/<p>/oracle-excluded.toml")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
