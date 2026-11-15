#!/usr/bin/env bash
# Self-test of the ui-scene and ui-fit judges (U06, docs/ui-judges.md), called by selftest/ui.sh: the canary app in
# selftest/ui_canary_product is built as a probe in release and san; `rigor ui-explore --judges ui-scene,ui-fit` replays
# the clean state and one state per check (canary.paths.json). Per check: exactly one finding of that check, with the id
# recomputed here from its identity, in its canary state, and no other finding there (the one stated extra of the wrap
# canary); no finding at all in the clean state; byte-identical findings across two runs and across release and san;
# every finding replays to its id; the contract's exceptions turn exactly their finding into info, and an unused or
# expired one is exception-unused; the judges refuse to run without a contract. No canary probe process is left.
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
  local var="$1" plat="$2" target="$3" log="$out/$step.$RANDOM.log" p
  "${B[@]}" build --target-platforms "$plat" "$target" --show-output 2>&1 | strip_ansi > "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}
CAT="$prod/canary.events.toml"
PATHS="$prod/canary.paths.json"
CONTRACT="$prod/canary.toml"
# judge <name> <wanted exit> <probe> <contract> [args...]: replays the canary paths with both judges
judge() {
  local name="$1" want="$2" bin="$3" contract="$4"; shift 4
  "${RIGOR[@]}" ui-explore --probe "$bin" --catalogue "$CAT" --strategy replay --paths "$PATHS" \
    --judges ui-scene,ui-fit --contract "$contract" --out "$out/j.$name.json" "$@" > "$out/j.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/j.$name.txt"
}

begin "c_ui_probe builds the probe of the canary app in release and in san"
build_out probe_rel "$REL" "$P:probe"
build_out probe_san "$SAN" "$P:probe"

begin "the judges on the canary: per check exactly one finding with its recomputed id in its canary state and nothing else there; nothing in the clean state"
judge rel.1 1 "$probe_rel" "$CONTRACT" --evidence "$out/ev.rel.1"
python3 -I - "$out/j.rel.1.json" "$PATHS" <<'PY' || fail "$CUR: the canary findings" "$out/j.rel.1.txt"
import hashlib, json, sys
found = [json.loads(line) for line in open(sys.argv[1])]
paths = json.load(open(sys.argv[2]))["paths"]
# canary event -> (gate, check, identity) of the one finding it must give (docs/ui-judges.md, "Canaries")
WANT = {
    "v-occluded": ("ui-scene", "occluded-target", ["ok"]),
    "v-overlay": ("ui-scene", "overlay-policy", ["veil", "ok", "captures"]),
    "v-small": ("ui-scene", "touch-target-small", ["ok", "dp"]),
    "v-spacing": ("ui-scene", "target-spacing", ["back", "ok", "hard"]),
    "v-bounds": ("ui-scene", "node-out-of-bounds", ["edge", "window"]),
    "v-overlap": ("ui-scene", "text-overlap", ["body", "title"]),
    "v-font": ("ui-scene", "font-below-min", ["body"]),
    "v-hierarchy": ("ui-scene", "hierarchy-violated", ["rank"]),
    "v-raw": ("ui-scene", "raw-text", ["body", "empty"]),
    "v-wrap": ("ui-scene", "wrap-policy-undeclared", ["body"]),
    "v-overflow": ("ui-fit", "text-overflow", ["body"]),
    "v-clipped": ("ui-fit", "text-clipped", ["ok"]),
    "v-dots": ("ui-fit", "full-string-shown", ["body"]),
    "v-unmeasurable": ("ui-fit", "fit-unmeasurable", ["body", "facts"]),
    "v-glyph": ("ui-fit", "glyph-missing", ["body"]),
    "v-unmatched": ("ui-scene", "stage-unmatched", ["scene", "ghost", "absent"]),
}
# the one stated extra: a text node without a wrap scope cannot be measured for overflow either
EXTRA = {"v-wrap": [("ui-fit", "fit-unmeasurable", ["body", "scope"])]}
def fid(gate, check, identity, key):
    data = json.dumps([gate, check, [identity, key]], sort_keys=True, separators=(",", ":")).encode() + b"\n"
    return "%s.%s/%s" % (gate, check, hashlib.sha256(data).hexdigest()[:12])
assert sorted(WANT) == sorted(p[-1] for p in paths[1:]) and paths[0] == ["open 1000000000 7"], "paths"
assert not [f for f in found if f["path"] == paths[0]], "a finding in the clean state: %r" % [f["id"] for f in found if f["path"] == paths[0]]
keys = {}
for path in paths[1:]:
    event = path[-1]
    here = [f for f in found if f["path"] == path]
    assert here and len({f["state"]["key"] for f in here}) == 1, "%s: no finding or several states" % event
    key = here[0]["state"]["key"]
    keys[event] = key
    want = [WANT[event]] + EXTRA.get(event, [])
    got = sorted((f["gate"], f["check"], f["id"]) for f in here)
    expected = sorted((g, c, fid(g, c, i, key)) for g, c, i in want)
    assert got == expected, "%s: got %r, wanted %r" % (event, got, expected)
    gate, check, _ = WANT[event]
    assert len([f for f in here if f["check"] == check]) == 1
assert len(set(keys.values())) == len(keys), "two canary states share a key"
assert len(found) == len(WANT) + 1, "%d findings" % len(found)
severity = {f["check"]: f["severity"] for f in found if f["check"] != "fit-unmeasurable"}
assert severity.pop("stage-unmatched") == "info" and set(severity.values()) == {"error"}
print("  %d checks, one canary state each, ids recomputed; the clean state has none" % len(WANT))
PY

begin "byte-identical findings: two release runs, and release against san"
judge rel.2 1 "$probe_rel" "$CONTRACT" --evidence "$out/ev.rel.2"
judge san.1 1 "$probe_san" "$CONTRACT" --evidence "$out/ev.san.1"
cmp -s "$out/j.rel.1.json" "$out/j.rel.2.json" || fail "$CUR: two release runs differ"
cmp -s "$out/j.rel.1.json" "$out/j.san.1.json" || fail "$CUR: release and san differ"
diff -r "$out/ev.rel.1" "$out/ev.rel.2" > "$out/ev.diff" || fail "$CUR: the evidence of two release runs differs" "$out/ev.diff"

begin "every finding replays from its evidence paths to its id"
n=0
for ident in $(python3 -I -c 'import json,sys; [print(json.loads(l)["id"].rsplit("/",1)[1]) for l in open(sys.argv[1])]' "$out/j.rel.1.json"); do
  dir="$out/ev.rel.1/$ident"
  [ -f "$dir/paths.json" ] && [ -f "$dir/records.json" ] || fail "$CUR: no evidence paths or records for $ident" "$out/j.rel.1.txt"
  "${RIGOR[@]}" ui-explore --probe "$probe_rel" --catalogue "$CAT" --strategy replay --paths "$dir/paths.json" \
    --judges ui-scene,ui-fit --contract "$CONTRACT" --out "$out/rp.json" > "$out/rp.txt" 2>&1
  [ "$?" -le 1 ] || fail "$CUR: replay of $ident failed" "$out/rp.txt"
  grep -q "/$ident\"" "$out/rp.json" || fail "$CUR: the replay of $ident does not give $ident" "$out/rp.txt"
  n=$((n + 1))
done
[ "$n" = 17 ] || fail "$CUR: $n findings replayed, wanted 17"
echo "  $n findings replayed to their ids"

begin "exceptions: a live one turns exactly its finding into info with its expiry; an unused and an expired one are exception-unused"
{ cat "$CONTRACT"; cat <<'TOML'
[[exception]]
id = "x-small"
rule = "touch-target-small"
target = "ok"
reason = "selftest: a live exception"
expires = "2099-12-31"
provenance = "owner:D1"
[[exception]]
id = "x-unused"
rule = "text-overlap"
target = "nobody/none"
reason = "selftest: matches nothing"
expires = "2099-12-31"
provenance = "owner:D2"
[[exception]]
id = "x-expired"
rule = "node-out-of-bounds"
target = "edge"
reason = "selftest: expired"
expires = "2020-01-01"
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
bounds = [i for i, f in plain.items() if f["check"] == "node-out-of-bounds"]
assert exc[bounds[0]] == plain[bounds[0]], "an expired exception changed its finding"
unused = sorted((f["observed"]["exception"], f["observed"]["expired"]) for f in exc.values() if f["check"] == "exception-unused")
assert unused == [("x-expired", True), ("x-unused", False)], unused
others = set(exc) - set(plain)
assert len(others) == 2 and set(plain) - set(exc) == set()
assert all(exc[i] == plain[i] for i in plain if i not in small), "an exception touched another finding"
print("  x-small applied (info, expires 2099-12-31); x-unused and x-expired are exception-unused")
PY

begin "the judges need a contract and known names (exit 2)"
"${RIGOR[@]}" ui-explore --probe "$probe_rel" --catalogue "$CAT" --strategy replay --paths "$PATHS" --judges ui-scene \
  --out "$out/n.json" > "$out/n.txt" 2>&1
[ "$?" = 2 ] && grep -q "need --contract" "$out/n.txt" || fail "$CUR: --judges without --contract" "$out/n.txt"
"${RIGOR[@]}" ui-explore --probe "$probe_rel" --catalogue "$CAT" --strategy replay --paths "$PATHS" --judges ui-scene,ui-nope \
  --contract "$CONTRACT" --out "$out/n.json" > "$out/n.txt" 2>&1
[ "$?" = 2 ] && grep -q "distinct names of" "$out/n.txt" || fail "$CUR: an unknown judge" "$out/n.txt"

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
