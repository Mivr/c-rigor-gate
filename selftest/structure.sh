#!/usr/bin/env bash
# Self-test of `rigor structure` (T011): the `c_structure` facts on RE, and the recursion and size/complexity
# gate. The throwaway product is selftest/structure_product (copied to a scratch package). Every red case is a
# module of its own, so its finding is the only one; the green module sits at every limit and passes.
# Needs bash, python3 (stdlib), tools/buck2. STRUCTURE_COLD=1 stamps the sources with a fresh nonce so that
# nothing can come from the RE cache (the cold action count of the report).
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
scratch="selftest/scratch_st"
pkg="//selftest/scratch_st"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT
RIGOR=(gate/rigor)
PY=(python3 -I -B)

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# executed <log>: remote + local commands buck2 reports (cache hits are not counted)
executed() { awk '/Commands:/ { for (i = 1; i <= NF; i++) { if ($i == "remote:") r = $(i+1); if ($i == "local:") l = $(i+1) } gsub(/[^0-9]/, "", r); gsub(/[^0-9]/, "", l); print r + l; found = 1 } END { if (!found) print 0 }' "$1" | tail -1; }

rm -rf "$scratch"
cp -r selftest/structure_product "$scratch"
if [ -n "${STRUCTURE_COLD:-}" ]; then
  nonce="$(date +%s%N)-$$"
  for f in "$scratch"/*.c; do sed -i "\$ s|\$| /* nonce $nonce */|" "$f"; done
fi

GREEN="clean"
RED="selfrec mutual macrorec cleanuprec asmrec aliasrec len51 params7 nest5 fpcycle callbackcycle gotos linehide packed longline macrofn file501 splitbody"
OTHER="xa xb"
# Modules whose real build is refused before any fact exists.
IMPOSSIBLE="included stmtexprrec stmtnest"

targets() { local n; for n in "$@"; do printf '%s ' "$pkg:${n}_s"; done; }

build_all() {
  local log="$1" name path
  # shellcheck disable=SC2046
  run "$log" build $(targets $GREEN $RED $OTHER) --show-full-output || return 1
  rm -rf "$out/facts"; mkdir -p "$out/facts"
  for name in $GREEN $RED $OTHER; do
    path="$(awk -v t="$pkg:${name}_s" 'index($1, t) {print $2}' "$log" | tail -1)"
    [ -f "$path" ] || { echo "no facts for $name: '$path'" >&2; return 1; }
    cp "$path" "$out/facts/$name.json"
  done
}
# gate <name>... : run `rigor structure` on the facts of the named modules, all at the level in $LEVEL (L3)
gate() {
  rm -rf "$out/case"; mkdir -p "$out/case"
  : > "$out/policy.toml"
  local n
  for n in "$@"; do
    cp "$out/facts/$n.json" "$out/case/$n.json"
    printf '[module."%s:%s"]\n' "$pkg" "$n" >> "$out/policy.toml"
    [ -n "${LEVEL:-}" ] && printf 'level = "%s"\n' "$LEVEL" >> "$out/policy.toml"
  done
  "${RIGOR[@]}" structure --facts "$out/case" --policy "$out/policy.toml" --out "$out/result.json" > "$out/gate.log" 2>&1
  GATE_CODE=$?
}
json() { "${PY[@]}" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' "$out/result.json" "$1"; }
rules() { json 'sorted({f["rule"] for f in r["findings"]})'; }
nfind() { json 'len(r["findings"])'; }

# --------------------------------------------------------------------------------------
begin "build the structure facts of 22 modules on RE (cold if STRUCTURE_COLD=1)"
t0=$SECONDS
build_all "$out/build1.log" || fail "$CUR: buck2 build failed" "$out/build1.log"
COLD="$(executed "$out/build1.log")"
echo "    built in $((SECONDS - t0)) s, executed $COLD actions"

begin "GREEN: the module that sits at every limit passes with no finding"
LEVEL=L3 gate clean
[ "$GATE_CODE" = 0 ] || fail "$CUR: expected exit 0, got $GATE_CODE" "$out/gate.log"
[ "$(nfind)" = 0 ] || fail "$CUR: findings on the clean module" "$out/gate.log"
"${PY[@]}" - "$out/facts/clean.json" <<'PY' || fail "$CUR: the clean module is not at its limits"
import json, sys
funcs = {f["name"]: f for u in json.load(open(sys.argv[1]))["units"] for f in u["functions"]}
assert funcs["exact50"]["body_lines"] == 50, funcs["exact50"]
assert funcs["six_params"]["params"] == 6 and funcs["nest4"]["nesting"] == 4, funcs
assert funcs["apply"]["indirect"] and not funcs["twice"]["indirect"], funcs["apply"]
assert funcs["use_apply"]["refs"], "the address of twice() must be listed"
print("    exact50 = 50 lines, six_params = 6, nest4 = 4, apply() has an indirect call site, twice() is address-taken")
PY
echo "    $(json 'r["metadata"]["indirect_sites"]') / address taken: $(json 'r["metadata"]["address_taken"]')"

check_red() { # name rule value-or-empty
  local name="$1" rule="$2" value="${3:-}"
  LEVEL=L3 gate "$name"
  [ "$GATE_CODE" = 1 ] || fail "$CUR: $name passed (exit $GATE_CODE)" "$out/gate.log"
  [ "$(rules)" = "['$rule']" ] || fail "$CUR: $name gave $(rules), expected only $rule" "$out/gate.log"
  [ "$(nfind)" = 1 ] || fail "$CUR: $name gave $(nfind) findings" "$out/gate.log"
  if [ -n "$value" ]; then
    [ "$(json 'r["findings"][0]["value"]')" = "$value" ] || fail "$CUR: $name measured $(json 'r["findings"][0]["value"]'), expected $value"
    echo "    $name -> $rule: measured $value, limit $(json 'r["findings"][0]["limit"]')"
  else
    echo "    $name -> $rule"
  fi
}

begin "RED (B1): recursion is found, alone, however it is spelled"
check_red selfrec recursion
check_red mutual recursion
LEVEL=L3 gate mutual
[ "$(json 'sorted({c.split(" (")[1].split(":")[0] for c in r["findings"][0]["cycle"]})')" = "['selftest/scratch_st/ping.c', 'selftest/scratch_st/pong.c']" ] \
  || fail "$CUR: the cycle does not name both files"
echo "    mutual: cycle across two files: $(json 'r["findings"][0]["cycle"]')"
check_red macrorec recursion
check_red cleanuprec recursion
check_red asmrec recursion
check_red aliasrec recursion

begin "RED (B1): a cycle across two modules"
LEVEL=L3 gate xa xb
[ "$GATE_CODE" = 1 ] && [ "$(rules)" = "['recursion']" ] && [ "$(nfind)" = 1 ] || fail "$CUR: expected one recursion finding" "$out/gate.log"
echo "    $(json 'r["findings"][0]["cycle"]')"
LEVEL=L3 gate xa
[ "$GATE_CODE" = 0 ] || fail "$CUR: xa alone has no cycle, the callee is not in the product" "$out/gate.log"
echo "    xa alone: no cycle (a callee the product does not define is a leaf)"

begin "RED (B1): indirect calls: a pointer cycle, and a callback handed to code outside the product"
check_red fpcycle indirect-cycle-possible
check_red callbackcycle indirect-cycle-possible
echo "    callbackcycle sites: $(json 'r["findings"][0]["sites"]')"

begin "RED (B2): the limits, one case each, the boundary exact (50 passes in the green module, 51 fails)"
check_red len51 function-length 51
check_red linehide function-length 51
check_red file501 file-length 501
check_red params7 parameter-count 7
check_red nest5 nesting-depth 5
check_red gotos cyclomatic-complexity 17
check_red packed statement-count 61
check_red longline line-length 253
check_red macrofn macro-defined-function
check_red splitbody split-function-body

begin "levels: L2 allows 51 lines, L1 has no limit but recursion, L2 reports a possible pointer cycle as info"
LEVEL=L2 gate len51
[ "$GATE_CODE" = 0 ] && [ "$(nfind)" = 0 ] || fail "$CUR: len51 at L2 should pass" "$out/gate.log"
LEVEL=L1 gate len51 file501 params7
[ "$GATE_CODE" = 0 ] && [ "$(nfind)" = 0 ] || fail "$CUR: no limit at L1" "$out/gate.log"
LEVEL=L1 gate selfrec
[ "$GATE_CODE" = 1 ] && [ "$(rules)" = "['recursion']" ] || fail "$CUR: recursion must fail at L1" "$out/gate.log"
LEVEL=L2 gate fpcycle
[ "$GATE_CODE" = 0 ] && [ "$(rules)" = "['indirect-cycle-possible']" ] && [ "$(json 'r["findings"][0]["severity"]')" = info ] || fail "$CUR: fpcycle at L2 is an info" "$out/gate.log"
LEVEL= gate clean
[ "$GATE_CODE" = 0 ] && grep -q "treated as L3" "$out/gate.log" || fail "$CUR: no level means L3, with a note" "$out/gate.log"
echo "    ok (a policy entry without level: $(grep note "$out/gate.log"))"

begin "fail closed: a module without facts, facts without a module, a dependency without facts, a partial file"
cp "$out/facts/clean.json" "$out/case/clean.json"
printf '[module."%s:clean"]\nlevel = "L3"\n[module."%s:ghost"]\nlevel = "L3"\n' "$pkg" "$pkg" > "$out/policy.toml"
"${RIGOR[@]}" structure --facts "$out/case" --policy "$out/policy.toml" --out "$out/result.json" > "$out/gate.log" 2>&1
[ $? = 1 ] && [ "$(rules)" = "['policy-module-without-facts']" ] || fail "$CUR: a policy module without facts must fail" "$out/gate.log"
printf '[module."%s:other"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
"${RIGOR[@]}" structure --facts "$out/case" --policy "$out/policy.toml" --out "$out/result.json" > "$out/gate.log" 2>&1
[ $? = 1 ] && [ "$(rules)" = "['module-not-in-policy', 'policy-module-without-facts']" ] || fail "$CUR: facts without a policy module must fail" "$out/gate.log"
LEVEL=L3 gate xb
[ "$GATE_CODE" = 1 ] && [ "$(rules)" = "['missing-dep-facts']" ] || fail "$CUR: xb without the facts of its dependency xa must fail" "$out/gate.log"
"${PY[@]}" - "$out/facts/selfrec.json" "$out/case/partial.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["units"] = []
json.dump(d, open(sys.argv[2], "w"))
PY
rm -f "$out/case/clean.json"
printf '[module."%s:selfrec"]\nlevel = "L3"\n' "$pkg" > "$out/policy.toml"
"${RIGOR[@]}" structure --facts "$out/case" --policy "$out/policy.toml" --out "$out/result.json" > "$out/gate.log" 2>&1
[ $? = 2 ] || fail "$CUR: a facts file whose source has no unit must be exit 2" "$out/gate.log"
[ ! -e "$out/result.json" ] || [ "$(json 'r["status"]')" = FAIL ] || fail "$CUR: a stale result reads as PASS"
echo "    ok: findings for the first three, exit 2 for the partial file"

begin "IMPOSSIBLE: what the real build refuses never reaches the gate (#include of a .c, statement expressions)"
run "$out/inc.log" build "$pkg:included_s" && fail "$CUR: a source that includes another .c built" "$out/inc.log"
grep -q "'inc2.c' file not found" "$out/inc.log" || fail "$CUR: expected 'file not found'" "$out/inc.log"
echo "    included: 'inc2.c' file not found (only the source being compiled and declared headers are inputs)"
for n in stmtexprrec stmtnest; do
  run "$out/$n.log" build "$pkg:${n}_s" && fail "$CUR: $n built" "$out/$n.log"
  grep -q "Wgnu-statement-expression" "$out/$n.log" || fail "$CUR: expected -Wgnu-statement-expression for $n" "$out/$n.log"
  echo "    $n: refused by -Wpedantic -Werror (-Wgnu-statement-expression)"
done

begin "WARM: an unchanged tree executes no action"
build_all "$out/build2.log" || fail "$CUR: buck2 build failed" "$out/build2.log"
WARM="$(executed "$out/build2.log")"
[ "$WARM" = 0 ] || fail "$CUR: $WARM actions executed on an unchanged tree" "$out/build2.log"
echo "    0 actions executed"

begin "an edit that changes one source re-runs that module's actions only"
sed -i "\$ s|\$| /* edited $(date +%s%N)-$$ */|" "$scratch/selfrec.c"
build_all "$out/build3.log" || fail "$CUR: buck2 build failed" "$out/build3.log"
n="$(executed "$out/build3.log")"
echo "    executed $n actions (the unit of that source; the join too when the unit facts changed)"
[ "$n" -ge 1 ] && [ "$n" -le 3 ] || fail "$CUR: expected a handful of actions" "$out/build3.log"

begin "WARM again"
build_all "$out/build4.log" || fail "$CUR: buck2 build failed" "$out/build4.log"
[ "$(executed "$out/build4.log")" = 0 ] || fail "$CUR: actions executed on an unchanged tree" "$out/build4.log"
echo "    0 actions executed"

echo "elapsed ${SECONDS}s"
echo "selftest/structure.sh: all checks passed in $SECONDS s (cold build: $COLD actions, warm: $WARM)"
