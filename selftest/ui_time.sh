#!/usr/bin/env bash
# Self-test of the ui-time judge (U09, docs/ui-judges-time.md), called by selftest/ui.sh: the timed canary
# (selftest/ui_canary_product/timed*.c, one timed defect per intent and a clean dialog) is built as a probe in release
# and san; `rigor ui-explore --judges ui-time` replays timed.paths.json. Per variant: exactly its findings, the ids
# recomputed here from the identity and the state key, the target (kind or node) and the part; nothing on the clean
# dialog; every check reached verdicts and none is vacuous or blocked; the clean dialog's lifetime bracketed to one
# tick; byte-identical findings across two runs and across release and san; every finding replays to its id; the
# explorer without ui-time gives no ui-time finding and sends no extra run; no probe is left.
# Needs bash, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(python3 -I -B gate/rigor)
P="//selftest/ui_canary_product"
prod="selftest/ui_canary_product"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
CAT="$prod/timed.events.toml"
PATHS="$prod/timed.paths.json"
CONTRACT="$prod/time.toml"
TODAY=2026-11-16

step=0
fail() { echo "FAIL [time $step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[time $step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
build_out() {
  local var="$1" plat="$2" target="$3" log="$out/$step.$1.log" p
  "${B[@]}" build --target-platforms "$plat" "$target" --show-output 2>&1 | strip_ansi > "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}
# explore <name> <wanted exit> <probe> <paths> [args...]: replays paths under a wall budget, killed if it hangs
explore() {
  local name="$1" want="$2" bin="$3" paths="$4"; shift 4
  timeout -s KILL 300 "${RIGOR[@]}" ui-explore --probe "$bin" --catalogue "$CAT" --strategy replay --paths "$paths" \
    --budget-s 240 --out "$out/t.$name.json" "$@" > "$out/t.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/t.$name.txt"
}
judged() { local name="$1" want="$2" bin="$3"; shift 3
  explore "$name" "$want" "$bin" "$PATHS" --judges ui-time --contract "$CONTRACT" --today "$TODAY" "$@"; }

begin "c_ui_probe builds the probe of the timed canary in release and in san"
build_out probe_rel toolchains//:linux_release "$P:time_probe"
build_out probe_san toolchains//:linux_san "$P:time_probe"

begin "ui-time on the timed canary: per variant exactly its findings (ids recomputed, target, part), nothing on the clean dialog, every check judged, none vacuous or blocked, the clean lifetime within one tick"
judged rel.1 1 "$probe_rel" --evidence "$out/ev" --summary "$out/t.rel.1.sum"
python3 -I - "$out/t.rel.1.json" "$PATHS" "$out/t.rel.1.sum" <<'PY' || fail "$CUR: the timed canary findings" "$out/t.rel.1.txt"
import hashlib, json, sys
found = [json.loads(line) for line in open(sys.argv[1])]
paths = json.load(open(sys.argv[2]))["paths"]
summary = json.load(open(sys.argv[3]))
# variant -> (check, identity, target key, target) of the findings it must give (docs/ui-judges-time.md, "Canaries")
WANT = {
    "v-clean": [],
    "v-early": [("notice-lifetime-short", ["dialog"], "kind", "dialog")],
    "v-never": [("notice-lifetime-long", ["dialog"], "kind", "dialog"),
                ("countdown-wrong", ["dialog", "stalled"], "part", "stalled")],
    "v-flash": [("flash", ["flash", "panel"], "key", "flash")],
    "v-blink": [("flash", ["blink", "panel"], "key", "blink")],
    "v-skip": [("countdown-wrong", ["dialog", "stalled"], "part", "stalled")],
    "v-zero": [("countdown-wrong", ["dialog", "zero"], "part", "zero")],
    "v-start": [("countdown-wrong", ["dialog", "start"], "part", "start")],
    "v-silent": [("invisible-auto-transition", ["main", "detail"], "to", "detail")],
    "v-clock": [("clock-origin-divergence", ["origin", "v-clock", "semantic"], "part", "semantic")],
}
def fid(check, identity, key):
    data = json.dumps(["ui-time", check, [identity, key]], sort_keys=True, separators=(",", ":")).encode() + b"\n"
    return "ui-time.%s/%s" % (check, hashlib.sha256(data).hexdigest()[:12])
assert sorted(WANT) == sorted(p[1] for p in paths[1:]) and paths[0] == ["open 1000000000 7"], "paths"
errors = [f for f in found if f["severity"] == "error"]
assert all(f["gate"] == "ui-time" for f in found), [f["id"] for f in found if f["gate"] != "ui-time"]
got = sorted((f["path"][1], f["check"]) for f in errors)
want = sorted((v, check) for v, items in WANT.items() for check, _i, _k, _t in items)
assert got == want, (got, want)
for f in errors:
    (check, identity, name, target), = [w for w in WANT[f["path"][1]] if w[0] == f["check"]]
    assert f["id"] == fid(check, identity, f["state"]["key"]), (f["id"], check, identity)
    assert f["observed"][name] == target, (f["id"], name, f["observed"])
    assert f["evidence"] and f["evidence"][0].endswith("paths.json"), f["evidence"]
short = [f for f in errors if f["check"] == "notice-lifetime-short"][0]
assert short["state"]["key"] != found[0]["state"], "keyed by the state of the first appearance"
examined, = [f for f in found if f["check"] == "checks-examined"]
totals = examined["observed"]["totals"]
assert all(n > 0 for c, n in totals.items() if c != "notice-lifetime-short-floor"), totals
assert totals["notice-lifetime-short-floor"] == 0, totals            # the reading rate is decided here
assert not [f for f in found if f["check"] in ("check-vacuous", "check-blocked", "contract-pending")]
rows = {r["path"][1]: r for r in examined["observed"]["lifetimes"]}
clean = rows["v-clean"]
assert (clean["shown_more_than_ms"], clean["shown_at_most_ms"]) == (3999, 4000), clean
assert rows["v-never"]["shown_at_most_ms"] is None and rows["v-early"]["shown_at_most_ms"] == 1000, rows
assert examined["observed"]["cost"]["probe_runs"] > 0 and examined["observed"]["cost"]["origin_runs"] == 4 * 7
assert summary["findings"]["ui-time.flash"] == 2 and summary["findings"]["ui-time.countdown-wrong"] == 4, summary
PY

begin "determinism: byte-identical findings across two release runs and across release and san"
judged rel.2 1 "$probe_rel"
judged rel.3 1 "$probe_rel"
judged san.1 1 "$probe_san"
cmp -s "$out/t.rel.2.json" "$out/t.rel.3.json" || fail "$CUR: two release runs differ" "$out/t.rel.3.txt"
cmp -s "$out/t.rel.2.json" "$out/t.san.1.json" || fail "$CUR: release and san differ" "$out/t.san.1.txt"
python3 -I - "$out/t.rel.1.json" "$out/t.rel.2.json" <<'PY' || fail "$CUR: the run with evidence differs beyond its evidence"
import json, sys
a, b = ([dict(json.loads(line), evidence=[]) for line in open(name)] for name in sys.argv[1:3])
assert a == b
PY

begin "replay: every finding's paths.json gives its id again"
for dir in "$out"/ev/*/; do
  id="$(basename "$dir")"
  explore "replay.$id" 1 "$probe_rel" "$dir/paths.json" --judges ui-time --contract "$CONTRACT" --today "$TODAY"
  grep -q "/$id\"" "$out/t.replay.$id.json" || fail "$CUR: $id does not replay" "$out/t.replay.$id.txt"
done

begin "without ui-time: no ui-time finding, the same runs and fewer probe commands"
explore plain 0 "$probe_rel" "$PATHS" --summary "$out/t.plain.sum"
python3 -I - "$out/t.plain.json" "$out/t.plain.sum" "$out/t.rel.1.sum" <<'PY' || fail "$CUR: the plain run" "$out/t.plain.txt"
import json, sys
found = [json.loads(line) for line in open(sys.argv[1])]
plain, timed = json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
assert not [f for f in found if f["gate"] == "ui-time"], found
assert plain["runs"] == timed["runs"] and plain["cost"]["probe_commands"] < timed["cost"]["probe_commands"]
PY

begin "ui-time refuses to run without a contract"
explore nocontract 2 "$probe_rel" "$PATHS" --judges ui-time --today "$TODAY"
grep -q "need --contract" "$out/t.nocontract.txt" || fail "$CUR: no contract message" "$out/t.nocontract.txt"

begin "no timed canary probe is left"
for bin in "$probe_rel" "$probe_san"; do
  if pgrep -f "$bin" > /dev/null; then fail "$CUR: a probe $bin is still running"; fi
done
echo "ui_time: OK"
