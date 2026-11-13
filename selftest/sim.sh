#!/usr/bin/env bash
# Self-test of c_sim (T2G1, P330 §1): the runner, the world interface, seed identity and crash handling on the fixture
# product selftest/sim (a toy locker with one relay line and deliberate bugs). No invariants yet (T2G3/T2G4).
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

begin "a warm rebuild of the clean target executes 0 actions"
run "$out/warm.log" build --target-platforms "$REL" "$P/clean:sim" || fail "$CUR" "$out/warm.log"
run "$out/warm.log" build --target-platforms "$REL" "$P/clean:sim" || fail "$CUR" "$out/warm.log"
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the warm build"

echo "elapsed ${SECONDS}s"
echo "sim selftest: all $step steps passed"
