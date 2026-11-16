#!/usr/bin/env bash
# Self-test of the ui-scene, ui-fit and ui-render judges (U06, U07, docs/ui-judges.md, docs/ui-judges-render.md),
# called by selftest/ui.sh: the canary app in selftest/ui_canary_product (speaking the scene vocabulary of the real
# lockers kiosk) is built as a probe in release and san; `rigor ui-explore --judges ui-scene,ui-fit,ui-render --today`
# replays the clean state, one state per check and a
# correct modal dialog whose dimmed clickable scrim makes the background inert (canary.paths.json). Per check: exactly its findings, the ids recomputed here from the identity,
# in its canary state, and nothing else there; nothing in the clean state nor under the modal dialog; every check
# examined nodes (checks-examined) and none is check-vacuous; the summary counts the judges' findings; byte-identical
# findings across two runs and across release and san; every finding replays to its id; the contract's exceptions
# against --today; the judges refuse to run without a contract, a date, known names or a well-named [[input_layer]];
# the canary session passes as a
# c_ui_probe_session test in release and san. No canary probe is left.
# Needs bash, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(python3 -I -B gate/rigor)
REL=toolchains//:linux_release
SAN=toolchains//:linux_san
P="//selftest/ui_canary_product"
prod="selftest/ui_canary_product"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

step=0
fail() { echo "FAIL [judges $step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[judges $step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
build_out() {
  local var="$1" plat="$2" target="$3" log="$out/$step.$1.log" p
  "${B[@]}" build --target-platforms "$plat" "$target" --show-output 2>&1 | strip_ansi > "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}
CAT="$prod/canary.events.toml"
PATHS="$prod/canary.paths.json"
CONTRACT="$prod/canary.toml"
TODAY=2026-11-16
JUDGES=ui-scene,ui-fit,ui-render
# judge <name> <wanted exit> <probe> <contract> [args...]: replays the canary paths with the three judges
judge() {
  local name="$1" want="$2" bin="$3" contract="$4"; shift 4
  "${RIGOR[@]}" ui-explore --probe "$bin" --catalogue "$CAT" --strategy replay --paths "$PATHS" \
    --judges "$JUDGES" --contract "$contract" --today "$TODAY" --out "$out/j.$name.json" "$@" > "$out/j.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/j.$name.txt"
}

begin "c_ui_probe builds the probe of the canary app in release and in san"
build_out probe_rel "$REL" "$P:probe"
build_out probe_san "$SAN" "$P:probe"

begin "the canary session (session.in) under buck2 test in release and san (c_ui_probe_session): transcript byte-identical, exit 0, nothing on stderr"
for plat in "$REL" "$SAN"; do
  log="$out/sess.${plat##*:}.log"
  "${B[@]}" test --target-platforms "$plat" "$P:session_test" 2>&1 | strip_ansi > "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || fail "$CUR: the canary session test failed in $plat" "$log"
  grep -Eq "Pass 1\. Fail 0\." "$log" || fail "$CUR: the session summary in $plat is not one pass" "$log"
done

begin "the judges on the canary: per check exactly its finding, the id recomputed, in its canary state and nothing else there; nothing in the clean state nor under the correct modal dialog; every check examined nodes and none is vacuous"
judge rel.1 1 "$probe_rel" "$CONTRACT" --evidence "$out/ev.rel.1" --summary "$out/j.rel.1.sum"
python3 -I - "$out/j.rel.1.json" "$PATHS" "$out/j.rel.1.sum" <<'PY' || fail "$CUR: the canary findings" "$out/j.rel.1.txt"
import hashlib, json, sys
found = [json.loads(line) for line in open(sys.argv[1])]
paths = json.load(open(sys.argv[2]))["paths"]
summary = json.load(open(sys.argv[3]))
# canary event -> (gate, check, identity, stateless) of the findings it must give (docs/ui-judges.md, "Canaries")
WANT = {
    "v-occluded": [("ui-scene", "occluded-target", ["ok"], False)],
    "v-overlay": [("ui-scene", "overlay-policy", ["veil", "ok", "captures"], False)],
    "v-small": [("ui-scene", "touch-target-small", ["ok", "dp"], False)],
    "v-spacing": [("ui-scene", "target-spacing", ["back", "ok", "hard"], False)],
    "v-bounds": [("ui-scene", "node-out-of-bounds", ["edge", "window"], False)],
    "v-overlap": [("ui-scene", "text-overlap", ["body", "title"], False)],
    "v-font": [("ui-scene", "font-below-min", ["body"], False)],
    "v-hierarchy": [("ui-scene", "hierarchy-violated", ["rank"], False)],
    "v-raw": [("ui-scene", "raw-text", ["body", "empty"], False)],
    # a role the contract gives no wrap scope: the contract's gap, once per role per run (R9)
    "v-wrap": [("ui-scene", "contract-incomplete", ["role-wrap", "caption"], True)],
    "v-wrap-contra": [("ui-scene", "wrap-policy-undeclared", ["body", "contradicts"], False)],
    "v-overflow": [("ui-fit", "text-overflow", ["title"], False)],
    "v-clipped": [("ui-fit", "text-clipped", ["ok"], False)],
    # the DOTS long mode is also the label's long mode against its `default` scope (ui-render, L3)
    "v-dots": [("ui-fit", "full-string-shown", ["body"], False),
               ("ui-render", "flag-mismatch", ["body", "long-mode"], False)],
    "v-unmeasurable": [("ui-fit", "fit-unmeasurable", ["body", "facts"], False)],
    "v-glyph": [("ui-fit", "glyph-missing", ["body"], False)],
    "v-unmatched": [("ui-scene", "stage-unmatched", ["scene", "ghost", "absent"], False)],
    "v-toggle": [("ui-scene", "toggle-group-indistinct", ["language", "bg"], False)],
    "v-text": [("ui-scene", "stage-text-mismatch", ["scene", "body"], False)],
    "v-shrunk": [("ui-fit", "font-shrunk", ["body"], False)],
    "v-modal": [],
    "v-fake-inert": [("ui-scene", "occluded-target", ["ok"], False)],
    "v-unreachable": [("ui-scene", "occluded-target", ["bscrim"], False)],
    # U07: the ui-render judge (docs/ui-judges-render.md, "Canaries")
    "v-invisible": [("ui-render", "invisible-node", ["body", "node"], False)],
    "v-contrast": [("ui-render", "contrast-low", ["body", "below-large"], False)],
    "v-disabled": [("ui-render", "flag-mismatch", ["back", "disabled-clickable"], False)],
    "v-click": [("ui-render", "flag-mismatch", ["body", "clickable"], False)],
    "v-hidden": [("ui-render", "flag-mismatch", ["body", "hidden"], False)],
    "v-long": [("ui-render", "flag-mismatch", ["body", "long-mode"], False)],
    "v-align": [("ui-render", "align-mismatch", ["body"], False)],
    "v-line": [("ui-render", "line-height-mismatch", ["body"], False)],
    "v-noink": [("ui-render", "ink-unmeasurable", ["ok"], False)],
    # U07 fix-up 1: a covered text, a button whose label paints nothing, a text on its own fill
    "v-covered": [("ui-render", "invisible-node", ["title", "covered"], False)],
    "v-btn-text": [("ui-render", "invisible-node", ["ok", "text"], False)],
    "v-fill": [("ui-render", "contrast-low", ["body", "below-large"], False)],
}
# the part each canary finding must have (a flip of the part is a different defect)
PARTS = {"v-occluded": "covered", "v-fake-inert": "covered", "v-unreachable": "layer-unreachable",
         "v-overlay": "captures", "v-wrap-contra": "contradicts", "v-contrast": "below-large",
         "v-disabled": "disabled-clickable", "v-click": "clickable", "v-hidden": "hidden", "v-long": "long-mode",
         "v-line": "above", "v-invisible": "node", "v-covered": "covered", "v-btn-text": "text",
         "v-fill": "below-large"}
def fid(gate, check, identity, key, stateless):
    data = json.dumps([gate, check, identity if stateless else [identity, key]], sort_keys=True,
                      separators=(",", ":")).encode() + b"\n"
    return "%s.%s/%s" % (gate, check, hashlib.sha256(data).hexdigest()[:12])
assert sorted(WANT) == sorted(p[-1] for p in paths[1:]) and paths[0] == ["open 1000000000 7"], "paths"
run_level = [f for f in found if f["state"] is None and f["check"] in ("checks-examined", "check-vacuous")]
assert sorted((f["gate"], f["check"], f["severity"]) for f in run_level) == \
    [("ui-fit", "checks-examined", "info"), ("ui-render", "checks-examined", "info"),
     ("ui-scene", "checks-examined", "info")], run_level
for f in run_level:
    assert all(n > 0 for n in f["observed"]["totals"].values()), f["observed"]["totals"]
    assert f["observed"]["states"] == 36
found = [f for f in found if f not in run_level]
assert not [f for f in found if f["path"] == paths[0]], [f["id"] for f in found if f["path"] == paths[0]]
keys = {}
for path in paths[1:]:
    event = path[-1]
    here = [f for f in found if f["path"] == path]
    states = {f["state"]["key"] for f in here if f["state"] is not None}
    assert len(states) <= 1, "%s: several states" % event
    if not WANT[event]:
        assert here == [], "%s: %r" % (event, [f["id"] for f in here])
        continue
    key = states.pop() if states else None
    keys[event] = key
    got = sorted((f["gate"], f["check"], f["id"]) for f in here)
    expected = sorted((g, c, fid(g, c, i, key, st)) for g, c, i, st in WANT[event])
    assert got == expected, "%s: got %r, wanted %r" % (event, got, expected)
    if event in PARTS:
        assert [f["observed"]["part"] for f in here] == [PARTS[event]], (event, [f["observed"] for f in here])
assert len(set(v for v in keys.values() if v)) == len([v for v in keys.values() if v]), "two canary states share a key"
assert len(found) == sum(len(w) for w in WANT.values()), "%d findings" % len(found)
# every finding is an error (an unmeasured ink too: the judge fails closed)
assert {f["severity"] for f in found} == {"error"}
assert [f["observed"]["against"] for f in found if f["path"][-1] == "v-fill"] == ["own-fill"]
counts = summary["findings"]
assert counts["ui-scene.checks-examined"] == 1 and counts["ui-fit.font-shrunk"] == 1 and counts["intent-missed"] == 0
assert counts["ui-render.checks-examined"] == 1 and counts["ui-render.flag-mismatch"] == 5
assert counts["ui-render.invisible-node"] == 3 and counts["ui-render.ink-unmeasurable"] == 1
print("  %d canary states, the ids recomputed; nothing in the clean state nor under the correct modal dialog" % len(WANT))
PY

begin "without ui-render no ink command is sent and the ui-scene and ui-fit findings are the same"
printf '#!/bin/sh\ntee -a "%s" | "%s"\n' "$out/cmds.log" "$probe_rel" > "$out/logged-probe"
chmod +x "$out/logged-probe"
JUDGES=ui-scene,ui-fit judge two 1 "$out/logged-probe" "$CONTRACT"
grep -q '^frame$' "$out/cmds.log" || fail "$CUR: the logging probe saw no frame command" "$out/j.two.txt"
! grep -q '^ink' "$out/cmds.log" || fail "$CUR: an ink command without ui-render" "$out/cmds.log"
python3 -I - "$out/j.rel.1.json" "$out/j.two.json" <<'PY' || fail "$CUR: the two-judge findings differ" "$out/j.two.txt"
import json, sys
def load(name):
    """the findings without their evidence list (only the first run wrote evidence)"""
    return sorted(json.dumps(dict(f, evidence=[]), sort_keys=True) for f in map(json.loads, open(name)))
three = [f for f in load(sys.argv[1]) if json.loads(f)["gate"] != "ui-render"]
two = load(sys.argv[2])
assert three == two, (len(three), len(two))
print("  no ink command; %d ui-scene and ui-fit findings, identical" % len(two))
PY
JUDGES=ui-scene,ui-fit,ui-render

begin "byte-identical findings: two release runs, and release against san"
judge rel.2 1 "$probe_rel" "$CONTRACT" --evidence "$out/ev.rel.2"
judge san.1 1 "$probe_san" "$CONTRACT" --evidence "$out/ev.san.1"
cmp -s "$out/j.rel.1.json" "$out/j.rel.2.json" || fail "$CUR: two release runs differ"
cmp -s "$out/j.rel.1.json" "$out/j.san.1.json" || fail "$CUR: release and san differ"
diff -r "$out/ev.rel.1" "$out/ev.rel.2" > "$out/ev.diff" || fail "$CUR: the evidence of two release runs differs" "$out/ev.diff"

begin "every finding replays from its evidence paths to its id"
n=0
for ident in $(python3 -I -c 'import json,sys; [print(json.loads(l)["id"].rsplit("/",1)[1], int(json.loads(l)["state"] is not None)) for l in open(sys.argv[1])]' "$out/j.rel.1.json" | tr ' ' ':'); do
  stated="${ident#*:}"; ident="${ident%:*}"; dir="$out/ev.rel.1/$ident"
  [ -f "$dir/paths.json" ] || fail "$CUR: no evidence paths for $ident" "$out/j.rel.1.txt"
  [ "$stated" = 0 ] || [ -f "$dir/records.json" ] || fail "$CUR: no evidence records for $ident" "$out/j.rel.1.txt"
  "${RIGOR[@]}" ui-explore --probe "$probe_rel" --catalogue "$CAT" --strategy replay --paths "$dir/paths.json" \
    --judges "$JUDGES" --contract "$CONTRACT" --today "$TODAY" --out "$out/rp.json" > "$out/rp.txt" 2>&1
  [ "$?" -le 1 ] || fail "$CUR: replay of $ident failed" "$out/rp.txt"
  grep -q "/$ident\"" "$out/rp.json" || fail "$CUR: the replay of $ident does not give $ident" "$out/rp.txt"
  n=$((n + 1))
done
[ "$n" = 38 ] || fail "$CUR: $n findings replayed, wanted 38"
echo "  $n findings replayed to their ids"

begin "exceptions against --today: a live one turns exactly its finding into info with its expiry; an unused one is exception-unused, an error when its target was visited and info when not; an expired one is an error and changes nothing"
{ cat "$CONTRACT"; cat <<'TOML'
[[exception]]
id = "x-small"
rule = "touch-target-small"
target = "ok"
reason = "selftest: a live exception"
expires = "2099-12-31"
provenance = "owner:D1"
[[exception]]
id = "x-invisible"
rule = "invisible-node"
target = "body"
reason = "selftest: a live exception of a ui-render check"
expires = "2099-12-31"
provenance = "owner:D5"
[[exception]]
id = "x-seen"
rule = "raw-text"
target = "title"
reason = "selftest: its target is visited, it matches nothing"
expires = "2099-12-31"
provenance = "owner:D2"
[[exception]]
id = "x-unseen"
rule = "text-overlap"
target = "nobody/none"
reason = "selftest: its target is never visited"
expires = "2099-12-31"
provenance = "owner:D4"
[[exception]]
id = "x-expired"
rule = "node-out-of-bounds"
target = "edge"
reason = "selftest: expired"
expires = "2026-11-15"
provenance = "owner:D3"
TOML
} > "$out/exc.toml"
judge exc 1 "$probe_rel" "$out/exc.toml"
python3 -I - "$out/j.rel.1.json" "$out/j.exc.json" <<'PY' || fail "$CUR: the exception findings" "$out/j.exc.txt"
import json, sys
def load(name):
    """id -> finding, without the evidence list (only the first run wrote evidence)"""
    return {f["id"]: dict(f, evidence=[]) for f in map(json.loads, open(name))}
plain, exc = load(sys.argv[1]), load(sys.argv[2])
small = [i for i, f in plain.items() if f["check"] == "touch-target-small"]
assert len(small) == 1 and exc[small[0]]["severity"] == "info"
assert exc[small[0]]["observed"]["exception"] == {"id": "x-small", "expires": "2099-12-31"}
invisible = [i for i, f in plain.items() if f["check"] == "invisible-node" and f["observed"]["key"] == "body"]
assert len(invisible) == 1 and exc[invisible[0]]["severity"] == "info"
assert exc[invisible[0]]["observed"]["exception"] == {"id": "x-invisible", "expires": "2099-12-31"}
bounds = [i for i, f in plain.items() if f["check"] == "node-out-of-bounds"]
assert exc[bounds[0]] == plain[bounds[0]], "an expired exception changed its finding"
unused = sorted((f["observed"]["exception"], f["observed"]["expired"], f["observed"]["target_visited"], f["severity"])
                for f in exc.values() if f["check"] == "exception-unused")
assert unused == [("x-expired", True, True, "error"), ("x-seen", False, True, "error"),
                  ("x-unseen", False, False, "info")], unused
assert len(set(exc) - set(plain)) == 3 and set(plain) - set(exc) == set()
assert all(exc[i] == plain[i] for i in plain if i not in small + invisible), "an exception touched another finding"
print("  x-small and x-invisible applied (info, expires 2099-12-31); x-seen and x-expired errors, x-unseen info")
PY

begin "the judges need a contract, --today, known names and well-named [[input_layer]] rows (exit 2)"
refused() {
  local why="$1"; shift
  "${RIGOR[@]}" ui-explore --probe "$probe_rel" --catalogue "$CAT" --strategy replay --paths "$PATHS" \
    --out "$out/n.json" "$@" > "$out/n.txt" 2>&1
  [ "$?" = 2 ] && grep -q -- "$why" "$out/n.txt" || fail "$CUR: wanted exit 2 and '$why' for $*" "$out/n.txt"
}
refused "need --contract" --judges ui-scene --today "$TODAY"
refused "need --today" --judges ui-scene --contract "$CONTRACT"
refused "distinct names of" --judges ui-scene,ui-nope --contract "$CONTRACT" --today "$TODAY"
refused "only for --judges" --contract "$CONTRACT" --today "$TODAY"
refused "today" --judges ui-scene --contract "$CONTRACT" --today 2026-13-01
# a typo in an [[input_layer]] name would detach the row from every judge: the loader refuses it (U06 rule, U07 test)
sed 's/^layer = "banner"$/layer = "bnner"/' "$CONTRACT" > "$out/typo.toml"
cmp -s "$CONTRACT" "$out/typo.toml" && fail "$CUR: the typo contract is the contract"
refused "'bnner' names no layer role" --judges ui-render --contract "$out/typo.toml" --today "$TODAY"

begin "no canary probe process this selftest started is still alive"
python3 -I - "$probe_rel" "$probe_san" <<'PY' || fail "$CUR: canary probe processes left behind"
import os, sys, time
binaries = {os.path.realpath(b) for b in sys.argv[1:]}
def live():
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            state = open("/proc/%s/stat" % pid).read().rsplit(")", 1)[1].split()[0]
            exe = os.path.realpath("/proc/%s/exe" % pid)
        except OSError:
            continue
        if state != "Z" and exe in binaries:
            out.append(pid)
    return out
end = time.monotonic() + 5
while live() and time.monotonic() < end:
    time.sleep(0.05)
if live():
    print("alive:", live()); sys.exit(1)
PY
echo "  none"
echo "ui judges selftest passed"
