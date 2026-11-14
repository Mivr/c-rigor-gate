#!/usr/bin/env bash
# Self-test of c_sim (T2G1, P330 §1): the runner, the world interface, seed identity and crash handling on the fixture
# product selftest/sim (a toy locker with one relay line and deliberate bugs), plus the invariant engines of sim/inv (T2G3, T2G4, T2G5:
# their tests in both modes and their mutants at L3), and the coverage and soak of T2G6: what the seeds show, the soak of the fixture
# whose pool retires slots after 3 uses (red on I12, I13 and I11 on the days the arithmetic gives) and the judge over both.
# Needs bash, python3 (stdlib) and tools/buck2. Scratch lives under selftest/scratch_sim and $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(python3 -I -B gate/rigor)
MERGE=(python3 -I -B gate/rigor_lib/sim_merge.py)
REL=toolchains//:linux_release
SAN=toolchains//:linux_san
scratch="selftest/scratch_sim"
P="//selftest/scratch_sim"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# build_out <var> <platform> <target> [config...]: builds [sub]target, sets $var to its output file
build_out() {
  local var="$1" plat="$2" target="$3" log="$out/$step.$RANDOM.log" p; shift 3
  run "$log" build --target-platforms "$plat" "$@" "$target" --show-output || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}
# stat_of <file> <key>: a top-level key of the canonical stats JSON
stat_of() { python3 -I -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(json.dumps(v,sort_keys=True,separators=(",",":")) if isinstance(v,(list,dict)) else v)' "$1" "$2"; }
# rules_of <stats>: the sorted set of failure rules
rules_of() { python3 -I -c 'import json,sys; print(" ".join(sorted({f["rule"] for f in json.load(open(sys.argv[1]))["failures"]})))' "$1"; }
# world_sha <file>...: sha256 over the sorted content hashes of the files (as the run action computes it)
world_sha() { for f in "$@"; do sha256sum < "$f" | cut -d' ' -f1; done | LC_ALL=C sort | sha256sum | cut -d' ' -f1; }

rm -rf "$scratch"; mkdir -p "$scratch"
cp -R selftest/sim/. "$scratch/"
mkdir -p "$scratch/nobuild"
cp "$scratch/clean/BUCK" "$scratch/nobuild/BUCK"
{ cat "$scratch/clean/world.c"; echo '#error "this world does not build"'; } > "$scratch/nobuild/world.c"

begin "the runner's unit tests (SHA-256, seed derivation, trace hash, splitmix64, workload) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/unit.log" test --target-platforms "$plat" //sim:sim_unit_test || fail "$CUR: //sim:sim_unit_test failed in $plat" "$out/unit.log"
done

begin "the invariant engines (sim/inv: wire I3-I6b, events I1 I2 I9 I10 I15, audit scanner, views I7 I8 with the schema parser, the fixture kiosks with their seeded bugs) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/inv.log" test --target-platforms "$plat" //sim/inv/... || fail "$CUR: //sim/inv/... failed in $plat" "$out/inv.log"
  grep -Eq "Pass [0-9]+" "$out/inv.log" && ! grep -Eq "Fail [1-9]|Build failure [1-9]|Fatal [1-9]|Timeout [1-9]" "$out/inv.log" || fail "$CUR: the test summary in $plat is not a clean pass" "$out/inv.log"
done

begin "the invariant engines are mutation-tested at L3: every c_mutants target of sim/inv has zero survivors and uses no approval"
mkdir -p "$out/mut"
: > "$out/mut.toml"
for m in frame wire audit events ui; do
  build_out mrep "$REL" "//sim/inv:${m}_mutants"
  cp "$mrep" "$out/mut/$m.json"
  printf '[module."//sim/inv:%s_mutants"]\nlevel = "L3"\n' "$m" >> "$out/mut.toml"
done
"${RIGOR[@]}" mutants --results "$out/mut" --policy "$out/mut.toml" --out "$out/mut_result.json" > "$out/mut.txt" 2>&1 || fail "$CUR: rigor mutants rejects the sim/inv modules" "$out/mut.txt"
python3 -I - "$out/mut_result.json" <<'PY' || fail "$CUR: the mutant verdict is not a clean PASS: $(cat "$out/mut_result.json" | head -c 400)"
import json, sys
r = json.load(open(sys.argv[1]))
mods = r["metadata"]["modules"]
assert r["status"] == "PASS" and r["findings"] == [], r["findings"][:3]
assert sorted(mods) == ["//sim/inv:audit_mutants", "//sim/inv:events_mutants", "//sim/inv:frame_mutants", "//sim/inv:ui_mutants", "//sim/inv:wire_mutants"], sorted(mods)
assert r["metadata"]["approvals_used"] == [], "an approval was used"
for name, m in mods.items():
    assert m["survivors"] == [] and m["verdicts"]["survived"] == 0 and m["verdicts"]["unrun"] == 0 and m["total"] > 50, (name, m["verdicts"])
PY
echo "  $(python3 -I -c 'import json,sys; m=json.load(open(sys.argv[1]))["metadata"]["modules"]; print(", ".join("%s: %d mutants" % (k.split(":")[1], v["total"]) for k, v in sorted(m.items())))' "$out/mut_result.json")"

begin "the lockers view schema file is the text its test parses (the engine knows no product: the schema is the product's data)"
python3 -I - <<'PY' || fail "$CUR: selftest/sim/lockers-view.schema differs from LOCKERS_SCHEMA of sim/inv/tests/ui_lockers_test.c"
import re
src = open("sim/inv/tests/ui_lockers_test.c").read()
m = re.search(r"LOCKERS_SCHEMA\[\] =\n(.*?);\n", src, re.S)
lines = re.findall(r'^\s*"((?:[^"\\]|\\.)*)"\s*$', m.group(1), re.M)
text = "".join(l.replace('\\n', "\n").replace('\\"', '"').replace("\\\\", "\\") for l in lines)
assert text == open("selftest/sim/lockers-view.schema").read(), "differs"
PY

begin "clean world: 200 seeds PASS in release and san (2 shards), every seed run twice, 200 distinct trace hashes"
for plat in "$REL" "$SAN"; do
  run "$out/clean.log" test --target-platforms "$plat" "$P/clean:sim" || fail "$CUR: the clean world failed in $plat" "$out/clean.log"
  build_out st "$plat" "$P/clean:sim[stats]"; build_out vd "$plat" "$P/clean:sim[verdict]"; build_out hs "$plat" "$P/clean:sim[hashes]"
  [ "$(cat "$vd")" = pass ] || fail "$CUR: verdict is '$(cat "$vd")'"
  [ "$(stat_of "$st" seeds_run)" = 200 ] && [ "$(stat_of "$st" count)" = 200 ] && [ "$(stat_of "$st" distinct_hashes)" = 200 ] \
    && [ "$(stat_of "$st" failures)" = '[]' ] && [ "$(stat_of "$st" shards)" = 2 ] || fail "$CUR: stats: $(cat "$st")"
  [ "$(wc -l < "$hs")" = 200 ] || fail "$CUR: hashes file has $(wc -l < "$hs") lines"
  case "$plat" in "$REL") cp "$hs" "$out/clean.rel.hashes"; cp "$st" "$out/clean.rel.stats";; *) cp "$hs" "$out/clean.san.hashes";; esac
done
echo "  $(cat "$out/clean.rel.stats")" | cut -c1-200

begin "seeds are the derivation of P330 1.3: SHA-256(\"rigor-sim-v1\" || salt || world || le64(i)); release and san hashes are equal"
python3 -I - "$out/clean.rel.hashes" "$(world_sha "$scratch/clean/world.c")" <<'PY' || fail "$CUR: seed column differs from the reference derivation"
import hashlib, struct, sys
world = bytes.fromhex(sys.argv[2])
for line in open(sys.argv[1]).read().splitlines():
    index, seed = line.split(" ")[:2]
    want = int.from_bytes(hashlib.sha256(b"rigor-sim-v1" + world + struct.pack("<Q", int(index))).digest()[:8], "big")
    assert int(seed, 16) == want, (index, seed, hex(want))
PY
cmp -s "$out/clean.rel.hashes" "$out/clean.san.hashes" || fail "$CUR: release and san hashes differ: $(diff "$out/clean.rel.hashes" "$out/clean.san.hashes" | head -3)"
"${MERGE[@]}" compare "$out/clean.rel.hashes" "$out/clean.san.hashes" || fail "$CUR: the mode comparison reports a finding for the clean world"

begin "a salt (-c rigor.sim_salt) changes every seed and the salt hash, not the verdict"
build_out hs_salt "$REL" "$P/clean:sim[hashes]" -c rigor.sim_salt=0102
build_out st_salt "$REL" "$P/clean:sim[stats]" -c rigor.sim_salt=0102
[ "$(cut -d' ' -f2 "$hs_salt" | sort | comm -12 - <(cut -d' ' -f2 "$out/clean.rel.hashes" | sort) | wc -l)" = 0 ] || fail "$CUR: a seed survived the salt"
[ "$(stat_of "$st_salt" salt_sha256)" != "$(stat_of "$out/clean.rel.stats" salt_sha256)" ] || fail "$CUR: salt hash unchanged"
[ "$(stat_of "$st_salt" distinct_hashes)" = 200 ] || fail "$CUR: salted run is not 200 distinct"

begin "what the seeds showed (I11 to I14 checked, every fault fired and observed, the screens, the counters) is in the stats of the clean world, release and san"
for plat in "$REL" "$SAN"; do
  build_out st "$plat" "$P/clean:sim[stats]"
  python3 -I - "$st" <<'PY' || fail "$CUR: coverage of the clean world in $plat: $(head -c 600 "$st")"
import json, sys
s = json.load(open(sys.argv[1]))
inv = s["invariants"]
assert sorted(inv) == ["I11", "I12", "I13", "I14"], sorted(inv)
assert inv["I14"] == {"checked": 200, "violated": 0}, inv["I14"]
assert inv["I12"] == {"checked": 200, "violated": 0} and inv["I13"] == {"checked": 200, "violated": 0}, inv
assert inv["I11"] == {"checked": 0, "violated": 0}, "a 10 minute day has no sync upload: %s" % inv["I11"]
assert sorted(s["faults"]) == ["clock_jump", "disk_full", "relay_silent"], sorted(s["faults"])
for name, row in s["faults"].items():
    assert row["fired"] > 0 and row["observed"] > 0, (name, row)
assert s["screens"] == ["choose", "opened", "welcome"], s["screens"]
assert s["counters"]["no_free_blob"] == 0 and s["counters"]["save_failed"] > 0, s["counters"]
PY
done

begin "soak: the pool-retires-at-3 fixture goes red on I12, I13 and I11 on the days the arithmetic gives; the clean fixture stays green; release and san"
python3 -I - "selftest/sim/toy/toy.h" "selftest/sim/poolbug/world.c" > "$out/soak.expect" <<'PY' || fail "$CUR: cannot derive the expected days"
import math, re, sys
from fractions import Fraction
toy, world = open(sys.argv[1]).read(), open(sys.argv[2]).read()
slots = int(re.search(r"#define TOY_POOL_SLOTS (\d+)U", toy).group(1))
interval_ms = int(re.search(r"#define TOY_SYNC_INTERVAL_MS (\d+)ULL", toy).group(1))
retire = int(re.search(r"static const toy_hooks_t hooks = \{virtual_clock, no_bug, (\d+)\}", world).group(1))
interval = Fraction(interval_ms, 86400000)           # a sync interval, in days
usable = slots * retire                              # uploads the pool can serve: each slot retires at its `retire`-th use
last_good = usable * interval                        # the day the last snapshot is taken
# Day d is the checkpoint at the END of day d (virtual time d days), after every upload at or before it.
i12 = math.ceil(last_good)                           # the last slot is retired when that upload gives its blob back
i13 = math.ceil((usable + 1) * interval)             # the first upload that finds no blob
i11 = math.floor(last_good + 2 * interval) + 1       # snapshot age > 2 intervals (the book changes every few minutes)
print(i11, i12, i13)
PY
read -r exp11 exp12 exp13 < "$out/soak.expect"
[ "$exp12" = 3 ] && [ "$exp13" = 4 ] && [ "$exp11" = 5 ] || fail "$CUR: the arithmetic gives I11=$exp11 I12=$exp12 I13=$exp13, not the 5 3 4 of docs/sim.md: the fixture constants changed"
for plat in "$REL" "$SAN"; do
  build_out sk_bug "$plat" "$P/poolbug:sim[soak]" -c rigor.sim_soak_days=50
  build_out sk_ok "$plat" "$P/clean:sim[soak]" -c rigor.sim_soak_days=50
  python3 -I - "$sk_bug" "$sk_ok" "$exp11" "$exp12" "$exp13" <<'PY' || fail "$CUR: soak results in $plat: $(head -c 700 "$sk_bug")"
import json, sys
bug, ok = (json.load(open(p)) for p in sys.argv[1:3])
d11, d12, d13 = map(int, sys.argv[3:6])
assert bug["schema"] == "sim-soak/1" and bug["days"] == 50 and bug["uploads"] == 100, bug
got = {f["assertion"]: f["day"] for f in bug["failures"]}
assert got == {"I11": d11, "I12": d12, "I13": d13}, (got, d11, d12, d13)
assert [f["day"] for f in bug["failures"]] == sorted(f["day"] for f in bug["failures"]), "failures are in day order"
assert bug["checked"] == {"I11": 50, "I12": 50, "I13": 50}, bug["checked"]
assert ok["failures"] == [] and ok["days"] == 50 and ok["uploads"] == 100 and ok["checked"] == bug["checked"], ok
assert ok["seed"] != bug["seed"] and len(bug["seed"]) == 16
PY
  if [ "$plat" = "$REL" ]; then cp "$sk_bug" "$out/soak.bug.rel.json"; else cmp -s "$sk_bug" "$out/soak.bug.rel.json" || fail "$CUR: the soak differs between release and san"; fi
done

begin "the soak is built only when asked: without -c rigor.sim_soak_days (the merge tier) building it is an error, never an empty soak; the runner refuses a soak with seed options"
if run "$out/nosoak.log" build --target-platforms "$REL" "$P/clean:sim[soak]"; then fail "$CUR: a soak was built without days" "$out/nosoak.log"; fi
grep -q "no soak configured" "$out/nosoak.log" || fail "$CUR: no message about the missing soak days" "$out/nosoak.log"
run "$out/nosoak.log" build --target-platforms "$REL" "$P/clean:sim" || fail "$CUR: the test target needs no soak" "$out/nosoak.log"
if run "$out/badsoak.log" build --target-platforms "$REL" "$P/clean:sim[soak]" -c rigor.sim_soak_days=5000; then fail "$CUR: 5000 days accepted" "$out/badsoak.log"; fi
build_out soak_bin "$REL" "$P/clean:sim__bin"
for bad in "--soak-days 3 --count 2 --soak-out $out/x" "--soak-days 3" "--soak-days 3 --soak-out $out/x --stats $out/y" "--soak-out $out/x --stats $out/y --hashes $out/h --verdict $out/v --count 1 --run-ms 250" "--soak-days 5000 --soak-out $out/x"; do
  # shellcheck disable=SC2086
  "$soak_bin" --world-sha256 "$(printf '%064d' 0)" --step-limit 1000 --real-limit-s 5 $bad > "$out/badsoak.txt" 2>&1; [ "$?" = 2 ] || fail "$CUR: the runner accepted: $bad"
done
[ ! -e "$out/x" ] || fail "$CUR: a refused soak wrote its output"

begin "a soak whose world dies is a finding at the day it died, never a skip: a crashing world writes sim-crash, a runaway one sim-timeout"
build_out crash_bin "$REL" "$P/crash:sim__bin"
# the crash fixture dies on seeds with seed % 4 == 3: try worlds until the soak's seed is one (the soak itself must still finish)
for n in 0 1 2 3 4 5 6 7 8 9; do
  (ulimit -c 0; "$crash_bin" --world-sha256 "$(printf '%064d' "$n")" --soak-days 30 --step-limit 100000000 --real-limit-s 20 --soak-out "$out/crash.soak") > "$out/crash.txt" 2>&1 || fail "$CUR: runner exit $?" "$out/crash.txt"
  grep -q '"assertion":"sim-crash"' "$out/crash.soak" && break
done
build_out run_bin "$REL" "$P/runaway:sim__bin"
"$run_bin" --world-sha256 "$(printf '%064d' 0)" --soak-days 30 --step-limit 5000000 --real-limit-s 20 --soak-out "$out/run.soak" > "$out/run.txt" 2>&1 || fail "$CUR: runner exit $?" "$out/run.txt"
python3 -I - "$out/crash.soak" "$out/run.soak" <<'PY' || fail "$CUR: soak of a dying world"
import json, sys
crash, runaway = (json.load(open(p)) for p in sys.argv[1:3])
for doc in (crash, runaway):
    assert doc["days"] < 30 and doc["failures"], doc
assert crash["failures"][-1]["assertion"] == "sim-crash" and crash["failures"][-1]["day"] == 0, crash["failures"]
assert runaway["failures"][-1]["assertion"] == "sim-timeout" and runaway["failures"][-1]["day"] == runaway["days"] + 1, runaway
PY

begin "the judge over the real outputs: the buggy pool is red with the soak assertions and their days, the clean world is green, a short soak is soak-too-short, the merge tier wants none"
build_out s_clean "$REL" "$P/clean:sim[stats]"; build_out h_clean_rel "$REL" "$P/clean:sim[hashes]"; build_out h_clean_san "$SAN" "$P/clean:sim[hashes]"
build_out s_bug "$REL" "$P/poolbug:sim[stats]"; build_out h_bug_rel "$REL" "$P/poolbug:sim[hashes]"; build_out h_bug_san "$SAN" "$P/poolbug:sim[hashes]"
build_out v_clean "$REL" "$P/clean:sim[verdict]"; build_out v_bug "$REL" "$P/poolbug:sim[verdict]"
# the days are a config of the build, not of the output path: copy each soak before the next build overwrites it
build_out soak_clean "$SAN" "$P/clean:sim[soak]" -c rigor.sim_soak_days=50; cp "$soak_clean" "$out/soak.clean.50.json"; soak_clean="$out/soak.clean.50.json"
build_out soak_bug "$SAN" "$P/poolbug:sim[soak]" -c rigor.sim_soak_days=50; cp "$soak_bug" "$out/soak.bug.50.json"; soak_bug="$out/soak.bug.50.json"
build_out soak_bug3 "$SAN" "$P/poolbug:sim[soak]" -c rigor.sim_soak_days=3; cp "$soak_bug3" "$out/soak.bug.3.json"; soak_bug3="$out/soak.bug.3.json"
build_out jf_c "$REL" "$P/clean:sim_facts"; build_out jf_b "$REL" "$P/poolbug:sim_facts"
mkdir -p "$out/jf_clean" "$out/jf_bug"; cp "$jf_c" "$out/jf_clean/clean.json"; cp "$jf_b" "$out/jf_bug/poolbug.json"
python3 -I - "$out" "$s_clean" "$h_clean_rel" "$h_clean_san" "$v_clean" "$soak_clean" "$s_bug" "$h_bug_rel" "$h_bug_san" "$v_bug" "$soak_bug" "$soak_bug3" "$exp11" "$exp12" "$exp13" <<'PY' || fail "$CUR: judging the soak outputs"
import json, os, shutil, subprocess, sys
out, rest = sys.argv[1], sys.argv[2:]
(s_clean, hr_clean, hs_clean, v_clean, k_clean, s_bug, hr_bug, hs_bug, v_bug, k_bug, k_bug3), expect = rest[:11], tuple(map(int, rest[11:]))
SPEC = 'invariants = ["I12", "I13", "I14"]\nfaults = ["clock_jump", "disk_full", "relay_silent"]\nscreens = ["welcome", "choose", "opened"]\nzero_counters = ["no_free_blob"]\n'
BUGSPEC = 'invariants = ["I12", "I13", "I14"]\nzero_counters = ["no_free_blob"]\n'   # 20 second days: no screen or fault effect to ask for
CAP = '[soak.capacity.snapshot_pool]\nevent = "snapshot upload"\nbound = 6\nrate_per_day = 2\n'

def policy(seeds, nightly_days):
    return "[sim]\n[sim.seeds]\nmerge = %d\nnightly = %d\n[sim.soak_days]\nmerge = 0\nnightly = %d\n%s" % (seeds, seeds, nightly_days, CAP)

def judge(name, label, facts, files, pol, tier="nightly", spec=SPEC):
    d = os.path.join(out, "res_" + name); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    stats, hr, hs, verdict, soak = files
    for suffix, src in ((".stats.json", stats), (".release.hashes", hr), (".hashes", hs), (".verdict", verdict)):
        shutil.copy(src, os.path.join(d, "t000" + suffix))
    open(os.path.join(d, "t000.report"), "w").write("sim: report\n")
    if soak:
        shutil.copy(soak, os.path.join(d, "t000.soak.json"))
    json.dump({label: "t000"}, open(os.path.join(d, "index.json"), "w"))
    pf, sf, of = (os.path.join(out, name + e) for e in (".policy.toml", ".sim.toml", ".verdict.json"))
    open(pf, "w").write(pol); open(sf, "w").write(spec)
    code = subprocess.run([sys.executable, "-I", "-B", "gate/rigor", "sim", "--results", d, "--policy", pf, "--facts", facts,
                           "--spec", sf, "--tier", tier, "--out", of], capture_output=True, text=True).returncode
    return code, json.load(open(of))["findings"] if os.path.exists(of) else None

def rules(findings):
    return sorted({f["rule"] for f in findings})

CLEAN, BUG = "//selftest/scratch_sim/clean:sim", "//selftest/scratch_sim/poolbug:sim"
fc, fb = os.path.join(out, "jf_clean"), os.path.join(out, "jf_bug")
clean = (s_clean, hr_clean, hs_clean, v_clean, k_clean)
bug = (s_bug, hr_bug, hs_bug, v_bug, k_bug)

code, found = judge("clean", CLEAN, fc, clean, policy(200, 50))
assert code == 0 and found == [], (code, found)
code, found = judge("clean_merge", CLEAN, fc, clean[:4] + (None,), policy(200, 50), tier="merge")
assert code == 0 and found == [], ("the merge tier asks for no soak", code, found)
code, found = judge("clean_nosoak", CLEAN, fc, clean[:4] + (None,), policy(200, 50))
assert code == 1 and rules(found) == ["soak-too-short"], (code, found)

code, found = judge("bug", BUG, fb, bug, policy(20, 50), spec=BUGSPEC)
assert code == 1 and rules(found) == ["soak-assertion"], (code, found)
days = {f["assertion"]: f["day"] for f in found}
assert days == {"I11": expect[0], "I12": expect[1], "I13": expect[2]}, (days, expect)

# the sizing rule: 2 * 6 uploads at 2 per day need 6 days, whatever the tier asks; 3 days are too short
code, found = judge("short", BUG, fb, bug[:4] + (k_bug3,), policy(20, 2), spec=BUGSPEC)
(item,) = [f for f in found if f["rule"] == "soak-too-short"]
assert code == 1 and (item["required_days"], item["days"]) == (6, 3), (code, found)
# a spec that lists I11 (a 10 minute day never uploads): the seeds never reached it
code, found = judge("i11", CLEAN, fc, clean, policy(200, 50), spec=SPEC.replace('"I12"', '"I11", "I12"'))
assert code == 1 and [(f["rule"], f["invariant"]) for f in found] == [("sim-vacuous", "I11")], (code, found)
# a soak of another world is refused as malformed input
code, found = judge("mixed", CLEAN, fc, clean[:4] + (k_bug,), policy(200, 50))
assert code == 2, code
PY

begin "release-vs-san identity: a world whose behaviour depends on the build mode is sim-nondeterministic on seeds 0 to 9"
run "$out/mode.log" test --target-platforms "$REL" "$P/modediff:sim" || fail "$CUR: modediff must pass inside one mode" "$out/mode.log"
run "$out/mode.log" test --target-platforms "$SAN" "$P/modediff:sim" || fail "$CUR: modediff must pass inside one mode (san)" "$out/mode.log"
build_out mr "$REL" "$P/modediff:sim[hashes]"; cp "$mr" "$out/mode.rel"
build_out ms "$SAN" "$P/modediff:sim[hashes]"
found="$("${MERGE[@]}" compare "$out/mode.rel" "$ms")"; rc=$?
[ "$rc" = 1 ] && [ "$(printf '%s\n' "$found" | wc -l)" = 10 ] && printf '%s\n' "$found" | grep -q '"rule":"sim-nondeterministic"' || fail "$CUR: rc=$rc findings: $found"

begin "a nondeterministic world (a real clock behind a port) is sim-nondeterministic, with the first differing record"
if run "$out/nd.log" test --target-platforms "$REL" "$P/nondet:sim"; then fail "$CUR: the nondeterministic world passed" "$out/nd.log"; fi
build_out nd_st "$REL" "$P/nondet:sim[stats]"; build_out nd_vd "$REL" "$P/nondet:sim[verdict]"
[ "$(cat "$nd_vd")" = "fail sim-nondeterministic" ] || fail "$CUR: verdict '$(cat "$nd_vd")'"
[ "$(rules_of "$nd_st")" = sim-nondeterministic ] && grep -Eq '"detail":[0-9]+,"index"' "$nd_st" || fail "$CUR: stats: $(cat "$nd_st")"

begin "a crashing world (a null write on one seed in four) FAILS in release and in san; the other seeds still ran"
for plat in "$REL" "$SAN"; do
  if run "$out/crash.log" test --target-platforms "$plat" "$P/crash:sim"; then fail "$CUR: the crashing world passed in $plat" "$out/crash.log"; fi
  build_out cr_st "$plat" "$P/crash:sim[stats]"; build_out cr_vd "$plat" "$P/crash:sim[verdict]"
  [ "$(cat "$cr_vd")" = "fail sim-crash" ] && [ "$(rules_of "$cr_st")" = sim-crash ] || fail "$CUR: $plat verdict '$(cat "$cr_vd")' rules '$(rules_of "$cr_st")'"
  [ "$(stat_of "$cr_st" seeds_run)" = 20 ] || fail "$CUR: a crash stopped the run: seeds_run $(stat_of "$cr_st" seeds_run)"
  n="$(python3 -I -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["failures"]))' "$cr_st")"
  [ "$n" -ge 1 ] && [ "$n" -lt 20 ] || fail "$CUR: $n of 20 seeds failed"
done
build_out cr_rep "$SAN" "$P/crash:sim[report]"
grep -q "sim-crash" "$cr_rep" || fail "$CUR: the report does not name the rule" "$cr_rep"

begin "a runaway world (steps without time) is sim-timeout through the step limit"
if run "$out/run.log" test --target-platforms "$REL" "$P/runaway:sim"; then fail "$CUR: the runaway world passed" "$out/run.log"; fi
build_out rw_st "$REL" "$P/runaway:sim[stats]"; build_out rw_vd "$REL" "$P/runaway:sim[verdict]"
[ "$(cat "$rw_vd")" = "fail sim-timeout" ] && [ "$(rules_of "$rw_st")" = sim-timeout ] && [ "$(stat_of "$rw_st" seeds_run)" = 20 ] || fail "$CUR: verdict '$(cat "$rw_vd")': $(cat "$rw_st")"

begin "a hanging world is sim-timeout through the real-time limit of the runner; zero seeds is sim-no-seeds, never a pass"
build_out hang_bin "$REL" "$P/hang:sim__bin"
mkdir -p "$out/hang"
"$hang_bin" --world-sha256 "$(printf '%064d' 0)" --first 0 --count 2 --run-ms 20000 --step-limit 50000000 --real-limit-s 1 \
  --stats "$out/hang/stats" --hashes "$out/hang/hashes" --verdict "$out/hang/verdict" > "$out/hang/stdout" 2>&1 || fail "$CUR: runner exit $?" "$out/hang/stdout"
[ "$(cat "$out/hang/verdict")" = "fail sim-timeout" ] && [ "$(rules_of "$out/hang/stats")" = sim-timeout ] && [ "$(stat_of "$out/hang/stats" seeds_run)" = 2 ] || fail "$CUR: hang: $(cat "$out/hang/verdict") $(cat "$out/hang/stats")"
build_out clean_bin "$REL" "$P/clean:sim__bin"
mkdir -p "$out/zero"
"$clean_bin" --world-sha256 "$(printf '%064d' 0)" --first 0 --count 0 --run-ms 20000 --step-limit 50000000 --real-limit-s 5 \
  --stats "$out/zero/stats" --hashes "$out/zero/hashes" --verdict "$out/zero/verdict" > "$out/zero/stdout" 2>&1 || fail "$CUR: runner exit $?" "$out/zero/stdout"
[ "$(cat "$out/zero/verdict")" = "fail sim-no-seeds" ] || fail "$CUR: zero seeds gave '$(cat "$out/zero/verdict")'"
"$clean_bin" --count 1 > "$out/zero/usage" 2>&1; [ "$?" = 2 ] || fail "$CUR: a usage error must exit 2"

begin "a world that does not build is a failed build and a failed test, never a skip"
if run "$out/nb.log" build --target-platforms "$REL" "$P/nobuild:sim"; then fail "$CUR: the world built" "$out/nb.log"; fi
grep -q "this world does not build" "$out/nb.log" || fail "$CUR: no compile error in the log" "$out/nb.log"
if run "$out/nb.log" test --target-platforms "$REL" "$P/nobuild:sim"; then fail "$CUR: the test passed" "$out/nb.log"; fi

begin "kind matching: a c_sim world is a PRODUCT module for the other gates (kind c_sim); a denied symbol in its sources fails the symbols gate"
facts_of() { build_out "$1" "$REL" "$2"; }
facts_of f_clean "$P/clean:sim_facts"; facts_of f_den "$P/denied:sim_facts"; facts_of f_toy "$P/toy:toy_facts"; facts_of f_world //sim:world_facts
build_out libc "$REL" toolchains//:libc_symbols
grep -q '"kind":"c_sim"' "$f_clean" || python3 -I -c 'import json,sys; assert json.load(open(sys.argv[1]))["kind"]=="c_sim"' "$f_clean" || fail "$CUR: the facts kind is not c_sim"
mkdir -p "$out/fa" "$out/fb"
cp "$f_clean" "$out/fa/clean.json"; cp "$f_den" "$out/fb/denied.json"
for d in fa fb; do cp "$f_toy" "$out/$d/toy.json"; cp "$f_world" "$out/$d/world.json"; done
policy() { # policy <file> <world module>
  python3 -I - "$1" "$2" <<'PY'
import sys
src = open("products/selftest/policy.toml").read()
head = src.split("[module.")[0].replace('trusted = ["gate//ctest:ctest"]', "trusted = []")
mods = '''
[module."//selftest/scratch_sim/toy:toy"]
level = "L3"
impl = ["selftest/sim/toy/toy.c"]
allow = ["toy_variant"]
allow_mutable_data = true
exports = ["world_init", "world_run_until", "world_now_ms", "world_apply", "world_fault", "world_crash_restart", "world_stats", "world_state_hash"]

[module."//sim:world"]
allow = []
exports = []

[module."%s"]
allow = []
allow_mutable_data = true
exports = ["toy_variant"]
''' % sys.argv[2]
open(sys.argv[1], "w").write(head + mods)
PY
}
policy "$out/pa.toml" "$P/clean:sim"; policy "$out/pb.toml" "$P/denied:sim"
"${RIGOR[@]}" facts --gate symbols --facts "$out/fa" --policy "$out/pa.toml" --libc "$libc" --out "$out/sym_a.json" > "$out/sym_a.txt" 2>&1 || fail "$CUR: the clean world fails the symbols gate" "$out/sym_a.txt"
"${RIGOR[@]}" facts --gate symbols --facts "$out/fb" --policy "$out/pb.toml" --libc "$libc" --out "$out/sym_b.json" > "$out/sym_b.txt" 2>&1 && fail "$CUR: a denied symbol in a c_sim world passed the symbols gate" "$out/sym_b.txt"
grep -q '"rule":"denied-symbol"' "$out/sym_b.json" && grep -q '"symbol":"getenv"' "$out/sym_b.json" && grep -q "selftest/scratch_sim/denied:sim" "$out/sym_b.json" || fail "$CUR: wrong finding" "$out/sym_b.txt"
# Without a policy entry the world is an unjudged product module: the gate refuses it (fail closed).
printf '[global]\ndeny = ["getenv"]\n' > "$out/pc.toml"
"${RIGOR[@]}" facts --gate symbols --facts "$out/fb" --policy "$out/pc.toml" --libc "$libc" --out "$out/sym_c.json" > "$out/sym_c.txt" 2>&1 && fail "$CUR: a c_sim world with no policy entry passed" "$out/sym_c.txt"
grep -q '"rule":"module-not-in-policy"' "$out/sym_c.json" || fail "$CUR: no module-not-in-policy for the world" "$out/sym_c.txt"
"${RIGOR[@]}" facts --gate semantic-suppressions --facts "$out/fa" --policy "$out/pa.toml" --out "$out/sem_a.json" > "$out/sem_a.txt" 2>&1 || fail "$CUR: the clean world fails the semantic gate" "$out/sem_a.txt"

begin "buckfiles: a product BUCK that depends on a c_sim target or one it derives is refused (the real fixture BUCK files)"
mkdir -p "$out/bf/w" "$out/bf/user"
cp "$scratch/clean/BUCK" "$out/bf/w/BUCK"
"${RIGOR[@]}" buckfiles --root "$out/bf" --out "$out/bf.json" > "$out/bf.txt" 2>&1 || fail "$CUR: the c_sim BUCK itself is refused" "$out/bf.txt"
for dep in "//w:sim" "//w:sim__bin" "//w:sim__shard0" "//w:sim__soak" "//w:sim_facts"; do
  printf 'load("@gate//rules:c.bzl", "c_library")\nc_library(name = "u", srcs = ["u.c"], deps = ["%s"])\n' "$dep" > "$out/bf/user/BUCK"
  "${RIGOR[@]}" buckfiles --root "$out/bf" --out "$out/bf.json" > "$out/bf.txt" 2>&1 && fail "$CUR: a dep on $dep was accepted" "$out/bf.txt"
  grep -q '"why":"sim-target"' "$out/bf.json" || fail "$CUR: no sim-target finding for $dep" "$out/bf.txt"
done

begin "a warm rebuild of the clean target executes 0 actions"
run "$out/warm.log" build --target-platforms "$REL" "$P/clean:sim" || fail "$CUR" "$out/warm.log"
run "$out/warm.log" build --target-platforms "$REL" "$P/clean:sim" || fail "$CUR" "$out/warm.log"
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the warm build"

echo "elapsed ${SECONDS}s"
echo "sim selftest: all $step steps passed"
