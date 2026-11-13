"""Gate `mode-divergence` (T023, T138): the release compile of a product and its `san`, `msan` and `tsan` compiles
must contain the same code. (Below, `san` stands for each of the three; `rigor grade` compares the release facts
with each twin in turn, `run` takes the name of the mode as `mode_name`.)

`cscan.py` reads the `clang -E` output of one compile. Code under `__SANITIZE_ADDRESS__`,
`__has_feature(address_sanitizer)` (or `memory_sanitizer`, `thread_sanitizer`), `__SANITIZE_*__`, `NDEBUG` or `__OPTIMIZE__` is in that output in one mode only, so a
scan of the release compile alone cannot see what the `san` tests run. Every library, binary, test and
fuzz target therefore has a `<name>_facts_san` twin (rules/c.bzl), built from the `san` compile with the
very same scanner. This module compares the two, per unit, item by item.

Two roles in one file (stdlib only at import time, because the first one runs inside a Buck2 action
on RE with `python3 -I -B`):

* `scan` (action): the set of functions the preprocessed text calls, per unit, as `<name>.calls.json`.
  A call is an identifier followed by `(` in product text (a declaration or definition counts: a
  function that exists in one mode only is a divergence too). Same text and system-header rules as the
  fact scanner (it is a subclass of its collector).
* `compare` (`rigor facts --modes RELEASE_DIR SAN_DIR`): every semantic item of a unit (pragma, attribute,
  line directive, watched identifier incl. asm/builtins/macro directives, called function) present in
  one mode and not in the other is a finding `mode-divergent-code`, with the mode that has it, the file,
  the line and the item. Symbol facts are not compared: the san object legitimately differs.

What is not a divergence: text that comes from the gate's own toolchain headers, `<built-in>` and
`<command line>` (the sealed `-fsanitize` / `-O` flags and the macros they define) is never product
text. There is no policy knob: product code that differs between modes is a finding at every level.
Comments are gone after preprocessing in both modes, so a comment cannot differ.

A directory holds `<name>.json` (the facts file) and `<name>.calls.json` for each target. A missing
partner, a label mismatch, a target or a unit in one mode only, an unreadable or malformed file is
exit 2, never a pass. Gate-owned `c_third_party` facts are not compared.
"""

import argparse
import json
import os
import sys

GATE_ID = "mode-divergence"
SCHEMA = 1
CALLS_SUFFIX = ".calls.json"
# Identifiers followed by `(` that are not calls.
NOT_CALLS = frozenset("""
    _Alignas _Alignof _Atomic _Generic _Noreturn _Static_assert __attribute __attribute__ typeof
    __typeof__ __typeof
""".split())


def _cscan(path=None):
    """The fact scanner module: imported by the gate, loaded from `path` by the facts action (where each
    source file lies in a directory of its own)."""
    if path is None:
        from rigor_lib import cscan
        return cscan
    import importlib.util
    spec = importlib.util.spec_from_file_location("cscan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_collector(cscan):
    class CallCollector(cscan.Collector):
        def __init__(self, system_roots, vendor_markers=()):
            super().__init__(system_roots, vendor_markers)
            self.calls = set()
            self.pending = None
            self.skip = cscan.KEYWORDS | NOT_CALLS

        def scan_line(self, raw, where, attributes, gate=False):
            super().scan_line(raw, where, attributes, gate)
            for kind, tok in cscan.tokens(raw):
                if tok == "(" and self.pending is not None:
                    self.calls.add((self.pending,) + where)
                self.pending = tok if kind == "ident" and tok not in self.skip else None

    return CallCollector


def scan_main(argv):
    parser = argparse.ArgumentParser(prog="facts_modes scan", allow_abbrev=False)
    parser.add_argument("--label", required=True)
    parser.add_argument("--cscan", required=True, help="path of cscan.py")
    parser.add_argument("--system-root", action="append", default=[])
    parser.add_argument("--vendor-marker", action="append", default=[])
    parser.add_argument("--unit", nargs=2, action="append", default=[], metavar=("NAME", "PREPROCESSED"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    cscan = _cscan(args.cscan)
    units = []
    for name, path in sorted(args.unit):
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8", "replace")
        collector = _call_collector(cscan)(args.system_root, args.vendor_marker)
        collector.scan(text)
        units.append({"name": name, "calls": [{"name": n, "file": f, "line": line}
                                              for n, f, line in sorted(collector.calls)]})
    document = {"schema": SCHEMA, "label": args.label, "units": units}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with open(args.out, "wb") as handle:
        handle.write(text.encode("ascii") + b"\n")
    return 0


# ---------------------------------------------------------------------------------------------
# The comparison (rigor facts --modes)
# ---------------------------------------------------------------------------------------------

def _load_calls(path, label):
    from rigor_lib import jsonio
    from rigor_lib.errors import InternalError

    def bad(why):
        raise InternalError("%s: %s" % (path, why))

    try:
        doc = jsonio.strict_loads(jsonio.read_bytes(path))
    except ValueError as exc:
        raise InternalError("%s: not valid JSON: %s" % (path, exc)) from exc
    if not isinstance(doc, dict) or set(doc) != {"schema", "label", "units"}:
        bad("calls file must be an object with exactly schema, label, units")
    if type(doc["schema"]) is not int or doc["schema"] != SCHEMA:
        bad("unsupported schema")
    if doc["label"] != label:
        bad("calls file is for %r, its facts are for %r" % (doc["label"], label))
    if not isinstance(doc["units"], list):
        bad("units must be a list")
    units = {}
    for unit in doc["units"]:
        if not isinstance(unit, dict) or set(unit) != {"name", "calls"} or not isinstance(unit["name"], str) \
                or not isinstance(unit["calls"], list) or unit["name"] in units:
            bad("malformed unit")
        calls = set()
        for call in unit["calls"]:
            if not isinstance(call, dict) or set(call) != {"name", "file", "line"} \
                    or not isinstance(call["name"], str) or not isinstance(call["file"], str) \
                    or type(call["line"]) is not int or call["line"] < 0:
                bad("malformed call")
            calls.add(("call", call["name"], call["file"], call["line"]))
        units[unit["name"]] = calls
    return units


def load_mode_dir(directory):
    """label -> (kind, {unit name -> set of (kind, item, file, line)}) of one mode's directory."""
    from rigor_lib import facts_data, jsonio
    from rigor_lib.errors import InternalError
    if not os.path.isdir(directory):
        raise InternalError("modes path is not a directory: %s" % directory)
    names = sorted(os.listdir(directory))
    result, calls_files = {}, {}
    for name in names:
        full = os.path.join(directory, name)
        if not name.endswith(".json") or not os.path.isfile(full) or os.path.islink(full):
            raise InternalError("%s: not a facts file (only regular *.json files belong here)" % full)
        if name.endswith(CALLS_SUFFIX):
            calls_files[name[:-len(CALLS_SUFFIX)]] = full
            continue
        facts = facts_data.parse_facts(full, jsonio.read_bytes(full))
        if facts.label in result:
            raise InternalError("%s: second facts file for %s" % (full, facts.label))
        result[facts.label] = (name[:-len(".json")], facts)
    if not result:
        raise InternalError("no facts in %s" % directory)
    if {stem for stem, _ in result.values()} != set(calls_files):
        raise InternalError("%s: every facts file needs exactly one %s partner" % (directory, CALLS_SUFFIX))
    loaded = {}
    for label, (stem, facts) in result.items():
        if facts.kind == "c_third_party":
            continue
        calls = _load_calls(calls_files[stem], label)
        units = {}
        for unit in facts.units:
            items = set()
            items.update(("pragma", text, file, line) for file, line, text in unit.pragmas)
            items.update(("attribute", name, file, line) for name, file, line in unit.attributes)
            items.update(("identifier", name, file, line) for name, file, line in unit.identifiers)
            items.update(("line-directive", name, file, line) for name, file, line in unit.line_directives)
            if unit.name not in calls:
                raise InternalError("%s: no calls entry for unit %s" % (label, unit.name))
            items.update(calls.pop(unit.name))
            units[unit.name] = items
        if calls:
            raise InternalError("%s: calls for units the facts do not have: %s" % (label, sorted(calls)))
        loaded[label] = units
    return loaded


def compare(release, san, mode="san"):
    """Findings for two `load_mode_dir` results (`san` is the directory of the mode named `mode`: san, msan or tsan);
    anything that does not line up is InternalError."""
    from rigor_lib.errors import InternalError
    from rigor_lib.findings import finding
    if set(release) != set(san):
        raise InternalError("targets in one mode only: %s" % sorted(set(release) ^ set(san)))
    found = []
    for label in sorted(release):
        if set(release[label]) != set(san[label]):
            raise InternalError("%s: units in one mode only: %s"
                                % (label, sorted(set(release[label]) ^ set(san[label]))))
        for unit in sorted(release[label]):
            for mode, only in (("release", release[label][unit] - san[label][unit]),
                               (mode, san[label][unit] - release[label][unit])):
                for kind, item, file, line in sorted(only):
                    found.append(finding("mode-divergent-code", target=label, unit=unit, only_in=mode,
                                         item_kind=kind, item=item, file=file, line=line))
    return found


def run(args):
    """`args.modes`: the release and the other mode's directory; `args.mode_name` (default `san`) names the other."""
    from rigor_lib.findings import GateResult
    release = load_mode_dir(args.modes[0])
    san = load_mode_dir(args.modes[1])
    found = compare(release, san, getattr(args, "mode_name", "san"))
    units = sum(len(units) for units in release.values())
    return GateResult(GATE_ID, found, {"targets": len(release), "units": units})


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "scan":
        sys.exit("usage: facts_modes.py scan --label L --cscan cscan.py [--system-root R]... [--vendor-marker M]... --unit NAME PREPROCESSED --out F")
    sys.exit(scan_main(sys.argv[2:]))
