#!/usr/bin/env bash
# Self-test of the schema mutation engine (T124, docs/mutate-schema.md): `c_mutants_schema` on RE beside `c_mutants`.
# Builds the modules of selftest/mutate_schema/m with both engines and requires
#   1. every class disagreement between v1 and the schema engine to be explained (zero unexplained),
#   2. the schema engine's reports to be byte-identical when the whole run stage is made again (fresh nonce in the tests),
#   3. the generator's accounting to show each reason a mutant can leave the schema (constant context, string that
#      initialises an array, type change, schema-unviable by bisection) and `unreached` mutants.
# Needs bash, python3 (stdlib), tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
scratch="selftest/scratch_mutsch"
pkg="//selftest/scratch_mutsch/m"
out="$(mktemp -d)"
cleanup() { [ -d "$scratch" ] && mv "$scratch" "$out/scratch.moved"; return 0; }
trap cleanup EXIT
PY=(python3 -I -B)
MODULES=(elig pinned weak equiv multi macro attr lit rec fold hang)

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# path_of <log> <target name>: the report path a `--show-full-output` build printed
path_of() { awk -v t="$pkg:$2" '$1 == "root" t {print $2}' "$1" | tail -1; }

stamp() { # stamp <nonce>: a new comment at the end of every test source, so no test action can come from a cache
    for f in "$scratch"/m/*_test.c; do
        sed -i '/^\/\* nonce /d' "$f"
        printf '/* nonce %s */\n' "$1" >> "$f"
    done
}

begin "set up the throwaway package from selftest/mutate_schema/m"
mkdir -p "$scratch"
cp -r selftest/mutate_schema/m "$scratch/m"
mv "$scratch/m/BUCK.in" "$scratch/m/BUCK"
stamp "$(date +%s%N)-a"

targets=()
for m in "${MODULES[@]}"; do targets+=("$pkg:${m}_v1" "$pkg:${m}_schema"); done

begin "build every module with v1 and with the schema engine"
t0=$SECONDS
run "$out/build1.log" build "${targets[@]}" --show-full-output || fail "$CUR: buck2 build failed" "$out/build1.log"
echo "    built in $((SECONDS - t0)) s"

begin "every disagreement between v1 and the schema engine is explained"
for m in "${MODULES[@]}"; do
    v1="$(path_of "$out/build1.log" "${m}_v1")"; sc="$(path_of "$out/build1.log" "${m}_schema")"
    [ -f "$v1" ] && [ -f "$sc" ] || fail "$CUR: no report for $m"
    "${PY[@]}" mutate/schema/schema_compare.py compare --v1 "$v1" --schema "$sc" --strict > "$out/cmp_$m.txt" \
        || fail "$CUR: unexplained disagreement in $m" "$out/cmp_$m.txt"
    sed -n 1p "$out/cmp_$m.txt"
done

begin "the accounting: reasons, bisection, unreached mutants, baselines reproduced, runs saved by reach"
sc="$(path_of "$out/build1.log" "elig_schema")"
"${PY[@]}" - "$sc" <<'PYEOF' || fail "$CUR: the elig report is not as expected"
import json, sys
s = json.load(open(sys.argv[1]))["summary"]
need = {"constant-context": 1, "array-string-init": 1, "type-change": 1, "schema-unviable": 1}
for reason, least in need.items():
    if s["not_eligible"].get(reason, 0) < least:
        sys.exit("no mutant left the schema for %r: %r" % (reason, s["not_eligible"]))
if s["classes"].get("unreached", 0) < 1 or not all(s["baseline_reproduced"].values()):
    sys.exit("expected unreached mutants and a reproduced baseline: %r" % s)
if s["schema_compiles"] < 3:
    sys.exit("the schema should have needed bisection: %r" % s)
print("    elig:", s["status"], s["not_eligible"], s["classes"])
PYEOF
for m in "${MODULES[@]}"; do
    sc="$(path_of "$out/build1.log" "${m}_schema")"
    "${PY[@]}" - "$sc" "$m" <<'PYEOF' || fail "$CUR: $m: baseline not reproduced, or no eligible mutant"
import json, sys
r = json.load(open(sys.argv[1]))
s = r["summary"]
if not all(s["baseline_reproduced"].values()) or s["status"].get("eligible", 0) == 0:
    sys.exit(1)
PYEOF
done

begin "the whole run stage again with a fresh nonce: byte-identical schema reports"
stamp "$(date +%s%N)-b"
sch=()
for m in "${MODULES[@]}"; do sch+=("$pkg:${m}_schema"); done
t0=$SECONDS
run "$out/build2.log" build "${sch[@]}" --show-full-output || fail "$CUR: second buck2 build failed" "$out/build2.log"
echo "    built in $((SECONDS - t0)) s"
for m in "${MODULES[@]}"; do
    a="$(path_of "$out/build1.log" "${m}_schema")"; b="$(path_of "$out/build2.log" "${m}_schema")"
    cp -f "$a" "$out/first_$m.json"
    cmp -s "$out/first_$m.json" "$b" || fail "$CUR: the schema report of $m differs between two builds"
done

echo "mutate_schema selftest: OK"
