#!/usr/bin/env bash
# Self-test of `rigor grade` (T005): builds a throwaway product repo from selftest/grade_product,
# grades one clean change end to end (real clone, Buck2 on RE) cold, warm, hostile, uncached and with an internal error,
# plus the witness (T039) and test-author (T041) steps;
# the red changes are canaries now (T053), and
# the pack checks that each fails in exactly the gates that should catch it.
# Needs bash, git, python3 (stdlib), ssh-keygen and tools/buck2. Scratch lives under $TMPDIR
# (default /var/tmp) and is removed on exit (set RIGOR_GRADE_KEEP=1 to keep it).
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TMPDIR="${TMPDIR:-/var/tmp}"
work="$(mktemp -d "$TMPDIR/rigor-grade.XXXXXX")"
repo="$work/repo"
rigor=(python3 -I -B gate/rigor)
product=products/selftest/product.toml

kill_daemons() {
  local t
  for t in "$work"/*/tree "$work"/*/tree-witness; do
    [ -f "$t/gate/tools/buck2" ] && (cd "$t" && bash gate/tools/buck2 kill >/dev/null 2>&1)
  done
  return 0
}
cleanup() {
  kill_daemons
  if [ "${RIGOR_GRADE_KEEP:-}" = 1 ]; then echo "kept $work"; else rm -rf "$work" 2>/dev/null || { chmod -R u+w "$work"; rm -rf "$work"; }; fi
}
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; exit 1; }
now() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.1f", b - a }'; }

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
export GIT_AUTHOR_NAME=selftest GIT_AUTHOR_EMAIL=selftest@example.invalid
export GIT_COMMITTER_NAME=selftest GIT_COMMITTER_EMAIL=selftest@example.invalid

# ---------------------------------------------------------------------------------------
# The product repo. A fresh nonce in a comment makes the first (cold) grading really execute
# its actions; the same head graded again must then execute none.
# ---------------------------------------------------------------------------------------
mkdir -p "$repo"
cp -r selftest/grade_product/. "$repo/"
printf '\n/* selftest nonce %s-%s */\n' "$(date +%s%N)" "$$" >> "$repo/core/core.c"
git -C "$repo" init -q -b main
git -C "$repo" add -A
git -C "$repo" commit -q -m base
base="$(git -C "$repo" rev-parse HEAD)"

cat > "$work/task.toml" <<'EOF'
id = "selftest"
allowed = ["core/**", "util/**", ".buckconfig", "extra/**", "third_party/**"]
EOF

# ---------------------------------------------------------------------------------------
# Edits: each runs inside $repo on top of base and changes one thing.
# ---------------------------------------------------------------------------------------
edit_clean() { printf '\n/* clean change */\n' >> core/core.c; }

# ---------------------------------------------------------------------------------------
# check_verdict <verdict.json> <expected "gate:rule" list, comma separated or empty> <exit code> [work dir]
# Each expected failing gate must carry the named finding rule; any other FAIL or NOT_RUN is wrong.
# ---------------------------------------------------------------------------------------
check_verdict() {
  python3 -I - "$1" "$2" "$3" "${4:-}" <<'EOF'
import json, sys
path, code, work = sys.argv[1], int(sys.argv[3]), sys.argv[4]
tokens = [t for t in sys.argv[2].split(",") if t]
expected = {t.split(":")[0] for t in tokens}
core = json.load(open(path))["core"]
got = {g["id"]: g["status"] for g in core["gates"]}
bad = {g for g, s in got.items() if s == "FAIL"}
not_run = {g for g, s in got.items() if s == "NOT_RUN"}
# A failed build means there are no results or facts to judge: those gates are NOT_RUN (still a failure).
# Mutation testing and fuzzing need a clean tree and green tests: they are NOT_RUN after any of these failed.
want_not_run = ({"tests-release", "tests-san", "semantic-suppressions", "symbols", "structure", "mode-divergence"}
                if "build" in expected else set())
if expected & {"assemble", "buckfiles", "build", "tests-release", "tests-san"}:
    want_not_run.update(("mutants", "fuzz"))
want_code = 1 if expected else 0
print("  " + " ".join("%s=%s" % (g, s) for g, s in got.items()) + "  overall=" + core["overall"])
ok = bad == expected and not_run == want_not_run and code == want_code and (core["overall"] == "PASS") == (not expected)
for token in tokens:
    gate, rule = token.split(":")
    rules = {f["rule"] for f in json.load(open("%s/results/%s.json" % (work, gate)))["findings"]}
    if rule not in rules:
        ok = False
        print("  gate %s lacks finding rule %s (has %s)" % (gate, rule, sorted(rules)))
if not ok:
    print("  EXPECTED failing gates %s (exit %d), got FAIL %s NOT_RUN %s (exit %d)" % (sorted(expected), want_code, sorted(bad), sorted(not_run), code))
    sys.exit(1)
EOF
}

# find_daemons <dir>: lists processes whose working directory is under <dir>
find_daemons() {
  python3 -I - "$1" <<'EOF'
import os, sys
root = os.path.realpath(sys.argv[1])
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        cwd = os.path.realpath(os.readlink("/proc/%s/cwd" % pid))
    except OSError:
        continue
    if cwd == root or cwd.startswith(root + os.sep):
        print(pid, cwd)
EOF
}

# run_case <name> <expected failing gates> [extra rigor args]; sets $verdict, $secs
run_case() {
  local name="$1" expected="$2" head code started; shift 2
  step=$((step + 1))
  echo "[$step] $name"
  git -C "$repo" checkout -q -f -B "case-$name" "$base"
  git -C "$repo" clean -q -fdx
  (cd "$repo" && "edit_${name//-/_}")
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "$name"
  head="$(git -C "$repo" rev-parse HEAD)"
  verdict="$work/$name.verdict.json"
  started="$(now)"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$head" --task "$work/task.toml" \
      --product "$product" --work "$work/$name" --out "$verdict" "$@" > "$work/$name.log" 2>&1
  code=$?
  secs="$(elapsed "$started")"
  echo "  exit $code, ${secs}s"
  check_verdict "$verdict" "$expected" "$code" "$work/$name" || { tail -n 30 "$work/$name.log" >&2; fail "$name"; }
  [ -z "$(find_daemons "$work/$name")" ] || fail "$name: a process is still running in the grading tree"
  last_head="$head"
}

# ---------------------------------------------------------------------------------------
# The red cases of this script moved into the canary pack (T053, R006 #1). They are not gone:
# `selftest/canaries.sh` runs each of them with an exact expectation. docs/grade.md has the same table.
# ---------------------------------------------------------------------------------------
cat <<'MAP'
red cases (formerly steps of this script) now live in the canary pack, `selftest/canaries.sh`:
  grade.sh case        canary
  outside-contract     outside-contract
  nolint               nolint
  buckconfig-hidden    buckconfig-hidden       (build.json holds unused-variable: "contains")
  buckconfig-plain     buckconfig-plain
  product-buck2        product-buck2           (the product's tools/buck2 never ran: "absent")
  failing-test         failing-test
  removed-test         removed-test
  deleted-target       deleted-target
  heap-overflow        heap-overflow
  kills                kills
  spliced-optnone      spliced-optnone
  raw-rule             raw-rule
  weak-test            weak-test
  hollow-module        hollow-module
  unviable-shape       unviable-shape
  new-module           new-module
  long-function        structure-length
  recursion            structure-recursion
  mode-divergent       mode-divergent
  ungraded-module      ungraded-module
  excluded-code        excluded-code
  stale-include        stale-include
  third-party-copy     third-party-copy
  case-collision       case-collision
this script keeps the property steps: cold, warm (+ signature), hostile environment, --uncached, internal error,
the witness steps (T039) and the test-author steps (T041; the canaries stub-passes-test and stub-green also cover them)
MAP

jget() { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); 
for k in sys.argv[2:]: d=d[k]
print(d)' "$@"; }

# 1. clean change, cold (fresh nonce: everything executes). The other steps need its result (cache, core_sha256).
run_case clean "" ; cold_secs="$secs"
cold_verdict="$verdict"
exec_cold="$(jget "$cold_verdict" metadata gate_metadata build executed_actions)"
[ "$exec_cold" -gt 0 ] || fail "cold run executed no actions: the nonce did not reach the build"
sha_cold="$(jget "$cold_verdict" core_sha256)"
python3 -I - "$cold_verdict" <<'EOF2' || fail "cold: the mutants gate did not mutate the modules it should"
import json, sys
m = json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]["mutants"]
mods = m["modules"]
for label, s in sorted(mods.items()):
    print("  mutants %s: total %d, %s" % (label, s["total"], {k: v for k, v in s["verdicts"].items() if v}))
assert set(mods) == {"//core:core", "//util:util"}, sorted(mods)
assert mods["//core:core"]["total"] > 0 and mods["//core:core"]["survivors"] == [], mods["//core:core"]
assert m["targets"].keys() == mods.keys(), m["targets"]
assert m["executed_actions"] > 0, m
EOF2
for gate in structure mode-divergence; do
  [ "$(jget "$cold_verdict" metadata gate_metadata "$gate" executed_actions)" -gt 0 ] \
    || fail "cold run executed no $gate actions: the nonce did not reach them"
done

# ---------------------------------------------------------------------------------------
# Witness steps (T039). A test-surface change (a comment in core_test.c) puts //core:core in the witness
# scope. The commits are made here, one after the other (they share $repo); the gradings run in parallel below.
# Witness bundles are made with gate/tools/witness.py from the commits: `bundle-base` is core.c of $base,
# `bundle-strong` the same plus a comment (a different file with the same behaviour), `bundle-head` the
# witness the head itself would give (identical to the head).
# Red witness cases (a witness that fails a test, a witness survivor, no bundle entry) are canaries (T040).
# ---------------------------------------------------------------------------------------
witness_tool=(python3 -I gate/tools/witness.py)
make_bundle() {  # make_bundle <commit> <out dir>
  "${witness_tool[@]}" from-commit --repo "$repo" --commit "$1" --module //core:core --paths core/core.c \
      --product selftest --out "$2" > "$2.log" 2>&1 || { cat "$2.log" >&2; fail "witness.py from-commit"; }
}
make_bundle "$base" "$work/bundle-base"
cp -r "$work/bundle-base" "$work/bundle-strong"
printf '\n/* witness: the same behaviour, another file */\n' >> "$work/bundle-strong/files/core/core.c"
git -C "$repo" checkout -q -f -B case-witness-tests "$base"
git -C "$repo" clean -q -fdx
printf '\n/* test-surface change %s */\n' "$$" >> "$repo/core/core_test.c"
git -C "$repo" add -A
git -C "$repo" commit -q -m witness-tests
witness_head="$(git -C "$repo" rev-parse HEAD)"
make_bundle "$witness_head" "$work/bundle-head"

# ---------------------------------------------------------------------------------------
# Test-author steps (T041, P002 Q2): role test-author, a head that adds core_pos (1 if value > 0, else 0) with a
# stub and a strong new test `core/pos`, graded against `bundle-ta` (core.c of $base plus the correct core_pos).
# The gate-owned inputs are a scratch copy of products/selftest, as a test author's own acceptance uses (P002 Q1):
# `ta-inputs` adds the new id to expected-tests.json with the old list as expected-tests.previous.json,
# `ta-inputs-old` has no new id. The scratch policy exports core_pos and lets //core:core_test call strcmp.
#
# The new test also checks core_pos(order_ac()), where order_ac() is strcmp("a", "c"): -2 from the C library in
# release, -1 from the ASan interceptor in san (a mode artefact on purpose, invisible to `mode-divergence`). The
# correct core_pos gives 0 for both, so the witness passes in both modes; a stub that is wrong only at -1 passes
# on the stub in release only, one that is wrong only at -2 in san only.
# ---------------------------------------------------------------------------------------
cat > "$work/ta-task.toml" <<'EOF'
id = "selftest"
allowed = ["core/**", "util/**", ".buckconfig", "extra/**", "third_party/**"]
role = "test-author"
EOF
ta_inputs() {  # ta_inputs <dir> <expected-tests.json text>
  mkdir -p "$1"
  cp products/selftest/product.toml "$1/product.toml"
  sed -e 's/^exports = \["core_add", /exports = ["core_add", "core_pos", /' \
      -e '/^\[module."\/\/core:core_test"\]$/,/^allow = / s/^allow = \[\]$/allow = ["strcmp"]/' \
      products/selftest/policy.toml > "$1/policy.toml"
  grep -q '"core_pos"' "$1/policy.toml" && grep -q 'allow = \["strcmp"\]' "$1/policy.toml" \
    || fail "ta_inputs: the scratch policy edit did not apply"
  cp products/selftest/expected-tests.json "$1/expected-tests.previous.json"
  printf '%s\n' "$2" > "$1/expected-tests.json"
}
ta_inputs "$work/ta-inputs" '{"ids": ["core/add", "core/pos", "core/sign", "util/ramp", "util/sum", "utilcore/pair"]}'
ta_inputs "$work/ta-inputs-old" "$(cat products/selftest/expected-tests.json)"
mkdir -p "$work/ta-inputs-none"
cp "$work/ta-inputs/product.toml" "$work/ta-inputs/policy.toml" "$work/ta-inputs/expected-tests.json" "$work/ta-inputs-none/"

ta_pos() {  # ta_pos <body lines>: appends core_pos to core/core.c
  printf '\nint core_pos(int value) {\n%s\n}\n' "$1" >> core/core.c
}
ta_head() {  # ta_head <name> <core_pos body> [sign-stub]: the header, the new test and the stub; sets $ta_<name>
  local name="$1" body="$2" sign="${3:-}"
  git -C "$repo" checkout -q -f -B "case-ta-$name" "$base"
  git -C "$repo" clean -q -fdx
  (
    cd "$repo" || exit 1
    sed -i 's|^int core_sign(int value);$|&\nint core_pos(int value);|' core/core.h
    ta_pos "$body"
    if [ "$sign" = sign-stub ]; then
      sed -i '/^int core_sign(int value) {$/,/^}$/c\int core_sign(int value) {\n    (void)value;\n    return -12345;\n}' core/core.c
      grep -q 'return -12345;' core/core.c || exit 1
    fi
    sed -i 's|^#include "core.h"$|#include <string.h>\n\n&|' core/core_test.c
    sed -i 's|^CTEST_SUITE("core", { "add", t_add }, { "sign", t_sign })$|/* strcmp("a", "c"): -2 in release (C library), -1 in san (ASan interceptor). */\nstatic int order_ac(void) {\n    char a[2] = {(char)core_add(97, 0), 0};\n    char c[2] = {(char)core_add(99, 0), 0};\n    return strcmp(a, c);\n}\n\nstatic void t_pos(ctest_t *t) {\n    CHECK_EQ_I64(t, core_pos(1), 1);\n    CHECK_EQ_I64(t, core_pos(9), 1);\n    CHECK_EQ_I64(t, core_pos(0), 0);\n    CHECK_EQ_I64(t, core_pos(-7), 0);\n    CHECK_EQ_I64(t, core_pos(order_ac()), 0);\n}\n\nCTEST_SUITE("core", { "add", t_add }, { "pos", t_pos }, { "sign", t_sign })|' core/core_test.c
    grep -q '{ "pos", t_pos }' core/core_test.c && grep -q 'int core_pos(int value);' core/core.h || exit 1
  ) || fail "ta_head $name: the edit did not apply"
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "ta-$name"
  printf -v "ta_${name//-/_}" '%s' "$(git -C "$repo" rev-parse HEAD)"
}
# The witness: core.c of $base plus the correct core_pos, as a bundle (never committed to a graded head).
git -C "$repo" checkout -q -f -B case-ta-witness "$base"
(cd "$repo" && ta_pos '    if (value > 0) {
        return 1;
    }
    return 0;')
git -C "$repo" commit -q -am ta-witness
make_bundle "$(git -C "$repo" rev-parse HEAD)" "$work/bundle-ta"
sentinel='    (void)value;
    return -12345;'
ta_head green "$sentinel"
ta_head release-pass '    if (value == -1) {
        return 1;
    }
    return value > 0 ? 1 : 0;'
ta_head san-pass '    if (value == -2) {
        return 1;
    }
    return value > 0 ? 1 : 0;'
ta_head timeout '    (void)value;
    for (;;) {
    }'
ta_head a018 "$sentinel" sign-stub

# Red property step (T069): the clean module plus an exported function the policy does not list. The policy is the
# product's own (clean exports only; steps that add a symbol grade against a scratch policy, as ta_inputs does),
# so `symbols` must report unexpected-export. The function goes into core_test.c (its module lists `main` only):
# an untested function in core.c would also fail `mutants`, and one in core.h is a test-surface change either way,
# so the grading carries bundle-base (the witness passes: the function is independent of core.c).
git -C "$repo" checkout -q -f -B case-extra-export "$base"
git -C "$repo" clean -q -fdx
(
  cd "$repo" || exit 1
  printf '\nvoid test_extra(void);\nvoid test_extra(void) {\n}\n' >> core/core_test.c
  grep -q 'void test_extra(void) {' core/core_test.c || exit 1
) || fail "extra-export: the edit did not apply"
git -C "$repo" add -A
git -C "$repo" commit -q -m extra-export
extra_export_head="$(git -C "$repo" rev-parse HEAD)"

# grade_ta <name> <head> <inputs dir> <expected "gate:rule" list>: a test-author grading against bundle-ta
grade_ta() {
  local name="$1" head="$2" inputs="$3" expected="$4"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$head" --task "$work/ta-task.toml" \
      --product "$inputs/product.toml" --work "$work/$name" --out "$work/$name.verdict.json" \
      --witness "$work/bundle-ta" > "$work/$name.log" 2>&1
  local code=$?
  check_verdict "$work/$name.verdict.json" "$expected" "$code" "$work/$name" || { tail -n 30 "$work/$name.log" >&2; return 1; }
  [ -z "$(find_daemons "$work/$name")" ] || { echo "$name: a process is still running" >&2; return 1; }
}
# ta_check <name> <python body>: asserts over the verdict `v`, its gate metadata `m` and result files `r(gate)`
ta_check() {
  python3 -I - "$work/$1.verdict.json" "$work/$1" <<EOF
import glob, json, os, sys
v = json.load(open(sys.argv[1]))
m = v["metadata"]["gate_metadata"]
def r(gate):
    return json.load(open(os.path.join(sys.argv[2], "results", gate + ".json")))
def rules(gate, severity="error"):
    return sorted((f["rule"], f.get("id"), f.get("mode")) for f in r(gate)["findings"] if f["severity"] == severity)
def statuses(mode, test_id):
    found = []
    for path in sorted(glob.glob(os.path.join(sys.argv[2], "test-results", mode, "*.jsonl"))):
        for line in open(path):
            item = json.loads(line) if line.strip() else {}
            if item.get("id") == test_id:
                found.append(item["status"])
    return found
s = m["tests-stub"]
print("  tests-stub: new %s, fail kinds release %s, san %s" % (s["new_ids"],
      {k: n for k, n in s["fail_kinds"]["release"].items() if n}, {k: n for k, n in s["fail_kinds"]["san"].items() if n}))
$2
EOF
}

# grade_witness <name> <head> <bundle dir or "-" for none> [extra rigor args]: a grading that must pass
grade_witness() {
  local name="$1" head="$2" bundle="$3" args=(); shift 3
  [ "$bundle" = "-" ] || args=(--witness "$bundle")
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$head" --task "$work/task.toml" \
      --product "$product" --work "$work/$name" --out "$work/$name.verdict.json" "${args[@]}" "$@" \
      > "$work/$name.log" 2>&1
  local code=$?
  check_verdict "$work/$name.verdict.json" "" "$code" "$work/$name" || { tail -n 30 "$work/$name.log" >&2; return 1; }
  [ -z "$(find_daemons "$work/$name")" ] || { echo "$name: a process is still running" >&2; return 1; }
}

# Steps that depend on nothing but the cold run run in parallel, each in its own work subdir (and so its
# own Buck2 daemon). Each writes its transcript to $work/<name>.out; they are printed in order afterwards.

step_warm() {  # same head in a fresh work dir: nothing executes; the verdict is signed
  local started code gate n
  ssh-keygen -q -t ed25519 -N "" -C selftest -f "$work/key" >/dev/null || fail "warm: ssh-keygen"
  started="$(now)"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
      --product "$product" --work "$work/warm" --out "$work/warm.verdict.json" --sign-key "$work/key" \
      > "$work/warm.log" 2>&1
  code=$?
  echo "  exit $code, $(elapsed "$started")s"
  check_verdict "$work/warm.verdict.json" "" "$code" || { tail -n 30 "$work/warm.log" >&2; fail "warm"; }
  echo "  build actions executed: cold $exec_cold, warm $(jget "$work/warm.verdict.json" metadata gate_metadata build executed_actions)"
  for gate in build symbols mutants structure mode-divergence; do
    n="$(jget "$work/warm.verdict.json" metadata gate_metadata "$gate" executed_actions)"
    [ "$n" = 0 ] || fail "warm run executed $n $gate actions"
  done
  [ "$sha_cold" = "$(jget "$work/warm.verdict.json" core_sha256)" ] || fail "core_sha256 differs between two runs of the same inputs"
  echo "  core_sha256 identical: $sha_cold"
  ssh-keygen -Y check-novalidate -n c-rigor-gate-verdict -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
    || fail "verdict.json.sig does not verify"
  ssh-keygen -Y check-novalidate -n c-rigor-gate -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
    && fail "verdict signature verifies under the wrong namespace"
  echo "  signature verifies (namespace c-rigor-gate-verdict only)"
}

step_tier() {  # T137: tier merge defers the L2 module's mutation (the checks run after the parallel steps)
  local started code
  started="$(now)"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
      --product "$product" --work "$work/tier-merge" --out "$work/tier-merge.verdict.json" --tier merge \
      > "$work/tier-merge.log" 2>&1
  code=$?
  echo "  exit $code, $(elapsed "$started")s"
  check_verdict "$work/tier-merge.verdict.json" "" "$code" "$work/tier-merge" || { tail -n 30 "$work/tier-merge.log" >&2; fail "tier merge"; }
  [ -z "$(find_daemons "$work/tier-merge")" ] || fail "tier merge: a process is still running"
}

step_hostile() {  # the pipeline ignores the inherited environment, down to core_sha256
  local started code
  mkdir -p "$work/evil-home/.buckconfig.d"
  printf '[buck2_re_client]\n  engine_address = grpc://127.0.0.1:1\n  cas_address = grpc://127.0.0.1:1\n[build]\n  execution_platforms = evil//:nothing\n' > "$work/evil-home/.buckconfig.local"
  cp "$work/evil-home/.buckconfig.local" "$work/evil-home/.buckconfig.d/evil"
  started="$(now)"
  env HOME="$work/evil-home" XDG_CONFIG_HOME="$work/evil-home" BUCK2_BIN=/bin/false BUCK2_TEST=1 BUCK_LOG=debug \
      LD_PRELOAD=/nonexistent/evil.so LD_LIBRARY_PATH=/nonexistent SSH_AUTH_SOCK=/nonexistent \
      https_proxy=http://127.0.0.1:1 ALL_PROXY=http://127.0.0.1:1 PYTHONPATH=/nonexistent \
      "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
      --product "$product" --work "$work/hostile" --out "$work/hostile.verdict.json" > "$work/hostile.log" 2>&1
  code=$?
  echo "  exit $code, $(elapsed "$started")s"
  check_verdict "$work/hostile.verdict.json" "" "$code" "$work/hostile" || { tail -n 30 "$work/hostile.log" >&2; fail "hostile environment"; }
  [ "$(jget "$work/hostile.verdict.json" core_sha256)" = "$sha_cold" ] || fail "core_sha256 changed under a hostile environment"
  echo "  core_sha256 identical to the clean run"
  [ -z "$(find_daemons "$work/hostile")" ] || fail "hostile: a process is still running"
}

step_uncached() {  # every action really runs on a worker, and the verdict says so
  local started code
  started="$(now)"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
      --product "$product" --work "$work/uncached" --out "$work/uncached.verdict.json" --uncached \
      > "$work/uncached.log" 2>&1
  code=$?
  echo "  exit $code, $(elapsed "$started")s"
  check_verdict "$work/uncached.verdict.json" "" "$code" "$work/uncached" || { tail -n 30 "$work/uncached.log" >&2; fail "uncached"; }
  [ -z "$(find_daemons "$work/uncached")" ] || fail "uncached: a process is still running"
}

step_internal() {  # an internal error (unreadable contract) is exit 2 and a FAIL verdict
  local code
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/no-such-task.toml" \
      --product "$product" --work "$work/internal" --out "$work/internal.verdict.json" > "$work/internal.log" 2>&1
  code=$?
  [ "$code" = 2 ] || fail "internal-error: exit $code instead of 2"
  python3 -I - "$work/internal.verdict.json" <<'EOF3' || fail "internal-error: verdict"
import json, sys
core = json.load(open(sys.argv[1]))["core"]
got = {g["id"]: g["status"] for g in core["gates"]}
print("  " + " ".join("%s=%s" % kv for kv in got.items()))
assert core["overall"] == "FAIL" and got["contract"] == "FAIL" and got["build"] == "NOT_RUN", got
EOF3
  [ -z "$(find_daemons "$work/internal")" ] || fail "internal-error: a process is still running"
}

step_witness_na() {  # a pure impl change with a bundle: the witness gates are not applicable, nothing extra runs
  grade_witness witness-na "$last_head" "$work/bundle-base" || fail "witness-na"
  python3 -I - "$work/witness-na.verdict.json" <<'EOF5' || fail "witness-na: wrong witness gates"
import json, sys
v = json.load(open(sys.argv[1]))
m = v["metadata"]["gate_metadata"]
assert v["core"]["inputs"]["witness_sha256"] is not None
for gate in ("witness-tests", "mutants-witness"):
    assert m[gate]["scope"] == [] if gate == "witness-tests" else m[gate]["modules"] == {}, m[gate]
    assert "executed_actions" not in m[gate], m[gate]
print("  witness scope is empty: the witness gates ran no action")
EOF5
}

step_witness_strong() {  # a test-surface change with a strong witness (another file, same behaviour)
  grade_witness witness-strong "$witness_head" "$work/bundle-strong" || fail "witness-strong"
  python3 -I - "$work/witness-strong.verdict.json" <<'EOF6' || fail "witness-strong: wrong witness gates"
import json, sys
m = json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]
t, u = m["witness-tests"], m["mutants-witness"]
print("  witness-tests: executed %d, cached %d; mutants-witness: executed %d, cached %d"
      % (t["executed_actions"], t["cached_actions"], u["executed_actions"], u["cached_actions"]))
assert t["judged"] == ["//core:core"] and t["equals_head"] is False, t
assert t["executed_actions"] > 0 and u["executed_actions"] > 0, (t, u)
s = u["modules"]["//core:core"]
assert s["total"] > 0 and s["survivors"] == [], s
EOF6
}

step_witness_equal() {  # a witness identical to the head: its results are the head's, with zero actions (cold, then warm)
  local pass
  for pass in cold warm; do
    grade_witness "witness-equal-$pass" "$witness_head" "$work/bundle-head" || fail "witness-equal-$pass"
    python3 -I - "$work/witness-equal-$pass.verdict.json" "$pass" <<'EOF7' || fail "witness-equal-$pass: wrong witness gates"
import json, sys
v = json.load(open(sys.argv[1]))
m = v["metadata"]["gate_metadata"]
t, u = m["witness-tests"], m["mutants-witness"]
print("  %s: head build executed %d cached %d; witness-tests executed %d cached %d; mutants-witness executed %d cached %d"
      % (sys.argv[2], m["build"]["executed_actions"], m["build"]["cached_actions"], t["executed_actions"],
         t["cached_actions"], u["executed_actions"], u["cached_actions"]))
assert t["equals_head"] is True and u["equals_head"] is True, (t, u)
assert (t["executed_actions"], t["cached_actions"], u["executed_actions"], u["cached_actions"]) == (0, 0, 0, 0)
assert u["modules"]["//core:core"]["total"] > 0
if sys.argv[2] == "warm":
    assert m["build"]["executed_actions"] == 0 and m["mutants"]["executed_actions"] == 0
EOF7
  done
}

step_ta_green() {  # a stub head with a correct witness: the test-author grade passes
  grade_ta ta-green "$ta_green" "$work/ta-inputs" "" || fail "ta-green"
  ta_check ta-green '
assert s["new_ids"] == ["core/pos"], s
assert s["fail_kinds"]["release"]["check"] == 1 and s["fail_kinds"]["san"]["check"] == 1, s
assert [f["rule"] for f in r("mutants")["findings"]] == ["not-applicable"], r("mutants")
assert m["witness-tests"]["judged"] == ["//core:core"] and m["witness-tests"]["equals_head"] is False, m["witness-tests"]
assert m["tests-release"]["statuses_judged"] is False and m["tests-san"]["statuses_judged"] is False
c = m["mutants-witness"]["modules"]["//core:core"]
assert c["total"] > 0 and c["survivors"] == [], c
print("  witness mutants of //core:core: total %d, no survivor" % c["total"])
' || fail "ta-green: wrong gates"
}

step_ta_release_pass() {  # the new test passes on the stub in release (the stub is wrong only at -1, a san input)
  grade_ta ta-release-pass "$ta_release_pass" "$work/ta-inputs" "tests-stub:test-passes-on-stub" || fail "ta-release-pass"
  ta_check ta-release-pass '
assert rules("tests-stub") == [("test-passes-on-stub", "core/pos", "release")], rules("tests-stub")
assert s["fail_kinds"]["san"]["check"] == 1, s
' || fail "ta-release-pass: wrong findings"
}

step_ta_san_pass() {  # the new test passes on the stub in san only (the stub is wrong only at -2, a release input)
  grade_ta ta-san-pass "$ta_san_pass" "$work/ta-inputs" "tests-stub:test-passes-on-stub" || fail "ta-san-pass"
  ta_check ta-san-pass '
assert rules("tests-stub") == [("test-passes-on-stub", "core/pos", "san")], rules("tests-stub")
assert s["fail_kinds"]["release"]["check"] == 1, s
' || fail "ta-san-pass: wrong findings"
}

step_ta_timeout() {  # a stub that never returns: the new test still fails on it (timeout), info stub-timeout
  grade_ta ta-timeout "$ta_timeout" "$work/ta-inputs" "" || fail "ta-timeout"
  ta_check ta-timeout '
assert rules("tests-stub", "info") == [("stub-timeout", "core/pos", "release"), ("stub-timeout", "core/pos", "san")], r("tests-stub")
assert s["fail_kinds"]["release"]["timeout"] == 1 and s["fail_kinds"]["san"]["timeout"] == 1, s
' || fail "ta-timeout: wrong findings"
}

step_ta_no_new() {  # the same stub head, but the expected list gains no id: no-new-tests (core/pos is only unexpected)
  grade_ta ta-no-new "$ta_green" "$work/ta-inputs-old" "tests-stub:no-new-tests" || fail "ta-no-new"
  ta_check ta-no-new '
assert rules("tests-stub") == [("no-new-tests", None, None)], rules("tests-stub")
for mode in ("release", "san"):
    gate = "tests-" + mode
    assert rules(gate) == [], (gate, rules(gate))
    assert [(f["rule"], f["id"], f["status"]) for f in r(gate)["findings"]] == [("unexpected-test", "core/pos", "fail")], r(gate)
' || fail "ta-no-new: wrong findings"
}

step_ta_a018() {  # A018 shape: core_sign is stubbed too, so the old core/sign fails on the head; the witness passes it
  grade_ta ta-a018 "$ta_a018" "$work/ta-inputs" "" || fail "ta-a018"
  ta_check ta-a018 '
for mode in ("release", "san"):
    assert statuses(mode, "core/sign") == ["fail"], (mode, statuses(mode, "core/sign"))
    assert rules("tests-" + mode) == [], rules("tests-" + mode)
assert s["new_ids"] == ["core/pos"], s
assert m["witness-tests"]["equals_head"] is False
print("  core/sign fails on the head in both modes; tests-release, tests-san and witness-tests pass")
' || fail "ta-a018: wrong findings"
}

step_ta_no_previous() {  # role test-author without expected-tests.previous.json: exit 2 before any build
  local code
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$ta_green" --task "$work/ta-task.toml" \
      --product "$work/ta-inputs-none/product.toml" --work "$work/ta-no-previous" \
      --out "$work/ta-no-previous.verdict.json" --witness "$work/bundle-ta" > "$work/ta-no-previous.log" 2>&1
  code=$?
  [ "$code" = 2 ] || fail "ta-no-previous: exit $code instead of 2"
  grep -q 'expected-tests.previous.json' "$work/ta-no-previous.log" || fail "ta-no-previous: no reason in the log"
  python3 -I - "$work/ta-no-previous.verdict.json" <<'EOF9' || fail "ta-no-previous: verdict"
import json, sys
core = json.load(open(sys.argv[1]))["core"]
got = {g["id"]: g["status"] for g in core["gates"]}
print("  " + " ".join("%s=%s" % kv for kv in got.items()))
assert core["overall"] == "FAIL" and got["contract"] == "FAIL" and got["build"] == "NOT_RUN", got
EOF9
  [ -z "$(find_daemons "$work/ta-no-previous")" ] || fail "ta-no-previous: a process is still running"
}

step_extra_export() {  # the clean policy lists exactly the clean exports: an unlisted one is unexpected-export
  local code
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$extra_export_head" --task "$work/task.toml" \
      --product "$product" --work "$work/extra-export" --out "$work/extra-export.verdict.json" \
      --witness "$work/bundle-base" \
      > "$work/extra-export.log" 2>&1
  code=$?
  check_verdict "$work/extra-export.verdict.json" "symbols:unexpected-export" "$code" "$work/extra-export" \
    || { tail -n 30 "$work/extra-export.log" >&2; fail "extra-export"; }
  python3 -I - "$work/extra-export/results/symbols.json" <<'EOF10' || fail "extra-export: wrong findings"
import json, sys
errs = sorted((f["rule"], f.get("message", "")[:80]) for f in json.load(open(sys.argv[1]))["findings"] if f["severity"] == "error")
print("  symbols errors:", errs)
assert [e[0] for e in errs] == ["unexpected-export"], errs
EOF10
  [ -z "$(find_daemons "$work/extra-export")" ] || fail "extra-export: a process is still running"
}

# ---------------------------------------------------------------------------------------
# The fuzz gate (T129). `products/selftest/` has no fuzz target and `products/**` is not ours to extend, so the step
# below grades a product of its own: the selftest product plus `fz/` (a c_fuzz harness that calls //core:core), a
# gate-owned input directory made from the selftest one (layout, task contract and policy gain `fz`; `//core:core`
# must be fuzzed, with a budget of 5000 runs). The harness depends on core.c, which carries the run's nonce, so the
# cold grade really runs the fuzz action and the repeat grade must execute none.
# ---------------------------------------------------------------------------------------
fuzz_in="$work/fuzz-inputs"
mkdir -p "$fuzz_in"
cp products/selftest/product.toml products/selftest/policy.toml products/selftest/expected-tests.json "$fuzz_in/"
sed -i 's|include = \["core/\*\*",|include = ["core/**", "fz/**",|' "$fuzz_in/product.toml"
sed -i '/^exports = \["core_add", "core_sign"\]$/a fuzz = true\nfuzz_runs = 5000' "$fuzz_in/policy.toml"
sed 's|"core/\*\*",|"core/**", "fz/**",|' "$work/task.toml" > "$work/task-fuzz.toml"
cat >> "$fuzz_in/policy.toml" <<'EOF'

[module."//fz:core_fuzz"]
allow = []
exports = ["LLVMFuzzerTestOneInput"]
EOF
grep -q '"fz/\*\*"' "$fuzz_in/product.toml" && grep -q '^fuzz_runs = 5000$' "$fuzz_in/policy.toml" && grep -q '"fz/\*\*"' "$work/task-fuzz.toml" \
  || fail "fuzz: the gate-owned inputs were not prepared"
git -C "$repo" checkout -q -f -B case-fuzz "$base"
git -C "$repo" clean -q -fdx
mkdir -p "$repo/fz"
cat > "$repo/fz/BUCK" <<'EOF'
load("@gate//rules:c.bzl", "c_fuzz")

c_fuzz(name = "core_fuzz", srcs = ["core_fuzz.c"], deps = ["//core:core"])
EOF
cat > "$repo/fz/core_fuzz.c" <<'EOF'
#include <stddef.h>
#include <stdint.h>

#include "core/core.h"

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

/* Adds the input bytes in pairs; the sum is only kept so that the calls stay. */
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    size_t i;
    int total = 0;
    for (i = 0; i + 1U < size; i += 2U) {
        total += core_add(data[i], data[i + 1U]);
    }
    return total == -1 ? -1 : 0;
}
EOF
git -C "$repo" add -A
git -C "$repo" commit -q -m "fuzz target"
fuzz_head="$(git -C "$repo" rev-parse HEAD)"

# T135: a graded c_fuzz target with a corpus and a budget. Four more heads on top of the fuzz one (the same harness):
# the corpus holds the input of the gate-owned `fuzz-regressions.json` (PASS, replayed), that input removed from the corpus
# (fuzz-regression-missing), a harness that crashes on it (fuzz-crash in phase replay) and `runs` below the policy (fuzz-short).
mkdir -p "$work/fuzz-reg-inputs"
cp "$fuzz_in/product.toml" "$fuzz_in/policy.toml" "$fuzz_in/expected-tests.json" "$work/fuzz-reg-inputs/"
fuzz_head_of() {  # fuzz_head_of <branch> <c_fuzz extra args> <files to write: seed regress>: a commit on top of $fuzz_head; sets $made
  git -C "$repo" checkout -q -f -B "$1" "$fuzz_head"
  git -C "$repo" clean -q -fdx
  mkdir -p "$repo/fz/corpus"
  case "$3" in *seed*) printf 'SEED\001' > "$repo/fz/corpus/seed";; esac
  case "$3" in *regress*) printf 'BOOM\007' > "$repo/fz/corpus/regress";; esac
  printf '%s\n' 'load("@gate//rules:c.bzl", "c_fuzz")' '' "c_fuzz(name = \"core_fuzz\", srcs = [\"core_fuzz.c\"], deps = [\"//core:core\"]$2)" > "$repo/fz/BUCK"
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "fuzz corpus case $1"
  made="$(git -C "$repo" rev-parse HEAD)"
}
regress_sha="$(printf 'BOOM\007' | sha256sum | cut -d' ' -f1)"
printf '{"//fz:core_fuzz": ["%s"]}\n' "$regress_sha" > "$work/fuzz-reg-inputs/fuzz-regressions.json"
both=', corpus = ["corpus/seed", "corpus/regress"]'
fuzz_head_of case-fuzz-corpus "$both" "seed regress"; corpus_head="$made"
fuzz_head_of case-fuzz-dropped ', corpus = ["corpus/seed"]' "seed"; dropped_head="$made"
# The crash head: the harness reads a 4-byte table at the index in byte 4 of an input that starts with 'B'.
fuzz_head_of case-fuzz-crash "$both" "seed regress"
sed -i 's|^    return total == -1 ? -1 : 0;|    if (size == 5U \&\& data[0] == 66) {\n        total += table[data[4]];\n    }\n&|; s|^int LLVMFuzzerTestOneInput(const uint8_t \*data, size_t size)$|static const uint8_t table[4] = {1, 2, 3, 4};\n\n&|' "$repo/fz/core_fuzz.c"
git -C "$repo" commit -q -a -m "fuzz corpus case crash: the harness reads out of bounds"
crash_head="$(git -C "$repo" rev-parse HEAD)"
fuzz_head_of case-fuzz-budget ', runs = 1000' ""; budget_head="$made"
git -C "$repo" cat-file -e "$corpus_head" && git -C "$repo" cat-file -e "$dropped_head" && git -C "$repo" cat-file -e "$crash_head" \
  && grep -q "total += table" <(git -C "$repo" show "$crash_head:fz/core_fuzz.c") || fail "fuzz corpus: the heads were not prepared"

grade_fuzz() {  # grade_fuzz <work name> [head [inputs dir [expected tokens]]]: the fuzz product; sets $code
  local head="${2:-$fuzz_head}" inputs="${3:-$fuzz_in}"
  "${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$head" --task "$work/task-fuzz.toml" \
      --product "$inputs/product.toml" --work "$work/$1" --out "$work/$1.verdict.json" > "$work/$1.log" 2>&1
  code=$?
  check_verdict "$work/$1.verdict.json" "${4:-}" "$code" "$work/$1" || { tail -n 30 "$work/$1.log" >&2; return 1; }
  [ -z "$(find_daemons "$work/$1")" ] || { echo "$1: a process is still running" >&2; return 1; }
}

step_fuzz() {  # a clean fuzz target: the gate passes and runs it; the same head again executes no fuzz action
  grade_fuzz fuzz-cold || fail "fuzz (cold)"
  python3 -I - "$work/fuzz-cold/results/fuzz.json" <<'EOF11' || fail "fuzz: wrong result of the cold grade"
import json, sys
r = json.load(open(sys.argv[1]))
m = r["metadata"]
t = m["targets"]["//fz:core_fuzz"]
print("  fuzz: %s, executed %d, cached %d, runs_done %d, corpus %d" % (r["status"], m["executed_actions"], m["cached_actions"], t["runs_done"], t["corpus_files"]))
assert r["status"] == "PASS" and m["required_modules"] == ["//core:core"], r
assert sorted(m["targets"]) == ["//fz:core_fuzz"] and t["runs_done"] >= 5000 and t["phase"] == "budget", m
assert m["executed_actions"] > 0, "the nonce did not reach the fuzz action"
assert [f["rule"] for f in r["findings"]] == ["fuzz-empty-corpus"] and r["findings"][0]["severity"] == "info", r["findings"]
EOF11
  grade_fuzz fuzz-warm || fail "fuzz (warm)"
  python3 -I - "$work/fuzz-cold.verdict.json" "$work/fuzz-warm.verdict.json" <<'EOF12' || fail "fuzz: the repeat grade ran fuzz actions"
import json, sys
c, w = (json.load(open(p)) for p in sys.argv[1:])
m = w["metadata"]["gate_metadata"]["fuzz"]
print("  fuzz repeat grade: executed %d, cached %d" % (m["executed_actions"], m["cached_actions"]))
assert m["executed_actions"] == 0 and m["cached_actions"] > 0, m
assert m["targets"] == c["metadata"]["gate_metadata"]["fuzz"]["targets"], m
assert c["core_sha256"] == w["core_sha256"], "core_sha256 differs between two runs of the same inputs"
EOF12
}

step_fuzz_corpus() {  # T135: corpus and `runs` of a graded c_fuzz target, end to end through `rigor grade`
  local r="$work/fuzz-reg-inputs"
  grade_fuzz fuzzc-replayed "$corpus_head" "$r" || fail "fuzz corpus (replayed)"
  python3 -I - "$work/fuzzc-replayed/results/fuzz.json" "$work/fuzzc-replayed.verdict.json" <<'EOF13' || fail "fuzz corpus: the regression input was not replayed"
import json, sys
r = json.load(open(sys.argv[1]))
t = r["metadata"]["targets"]["//fz:core_fuzz"]
print("  fuzz corpus: %s, corpus %d, replayed %d, phase %s" % (r["status"], t["corpus_files"], t["replayed"], t["phase"]))
assert r["status"] == "PASS" and r["findings"] == [], r
assert t["corpus_files"] == 2 and t["replayed"] == 2 and t["phase"] == "budget" and t["runs_done"] >= 5000, t
assert json.load(open(sys.argv[2]))["core"]["inputs"]["fuzz_regressions_sha256"], "the regression list is not bound into the verdict"
EOF13
  grade_fuzz fuzzc-dropped "$dropped_head" "$r" "fuzz:fuzz-regression-missing" || fail "fuzz corpus (dropped)"
  grade_fuzz fuzzc-crash "$crash_head" "$r" "fuzz:fuzz-crash" || fail "fuzz corpus (crash)"
  grade_fuzz fuzzc-budget "$budget_head" "$fuzz_in" "fuzz:fuzz-short" || fail "fuzz corpus (budget)"
  python3 -I - "$work/fuzzc-crash/results/fuzz.json" "$work/fuzzc-budget/results/fuzz.json" <<'EOF14' || fail "fuzz corpus: wrong findings"
import json, sys
c, b = (json.load(open(p)) for p in sys.argv[1:])
assert [(f["rule"], f["phase"]) for f in c["findings"]] == [("fuzz-crash", "replay")], c["findings"]
assert [f["rule"] for f in b["findings"]] == ["fuzz-empty-corpus", "fuzz-short"] or [f["rule"] for f in b["findings"]] == ["fuzz-short", "fuzz-empty-corpus"], b["findings"]
print("  fuzz corpus: crash in phase replay, runs below the policy budget is fuzz-short")
EOF14
}

names=(warm hostile uncached tier internal witness_na witness_strong witness_equal extra_export fuzz fuzz_corpus
       ta_green ta_release_pass ta_san_pass ta_timeout ta_no_new ta_a018 ta_no_previous)
labels=("clean, same head again in a fresh work dir (warm), signed" "hostile inherited environment" "clean, --uncached" "clean, --tier merge (the L2 module is deferred)" "internal-error"
        "pure impl change with a witness bundle (witness gates not applicable)" "test-surface change with a strong witness" "test-surface change with a witness identical to the head (cold, warm)"
        "clean module plus an unlisted exported function (unexpected-export)"
        "a clean c_fuzz target (the fuzz gate runs it), the same head again (no fuzz action)"
        "c_fuzz with a corpus: replayed (PASS), regression input dropped, crash in the replay, runs below the policy budget"
        "test-author: a stub head with a correct witness" "test-author: a new test passes on the stub in release" "test-author: a new test passes on the stub in san only"
        "test-author: a stub that times out (info stub-timeout)" "test-author: no new ids" "test-author: old tests fail on a stubbed function, the witness passes them (A018)"
        "test-author without expected-tests.previous.json (exit 2)")
pids=()
parallel_started="$(now)"
for n in "${names[@]}"; do
  ( "step_$n" ) > "$work/$n.out" 2>&1 &
  pids+=($!)
done
bad=""
for i in "${!names[@]}"; do
  n="${names[$i]}"
  wait "${pids[$i]}" || bad="$bad $n"
  step=$((step + 1))
  echo "[$step] ${labels[$i]}"
  cat "$work/$n.out"
done
parallel_secs="$(elapsed "$parallel_started")"
[ -z "$bad" ] || fail "failed steps:$bad"
echo "  parallel steps wall ${parallel_secs}s"

python3 -I - "$work/uncached.verdict.json" "$work/warm.verdict.json" <<'EOF4' || fail "uncached: wrong counts or flag"
import json, sys
u, w = (json.load(open(p)) for p in sys.argv[1:])
b = u["metadata"]["gate_metadata"]["build"]
print("  uncached: executed %d, cached %d" % (b["executed_actions"], b["cached_actions"]))
for gate in ("structure", "mode-divergence"):
    n = u["metadata"]["gate_metadata"][gate]
    print("  uncached %s: executed %d, cached %d" % (gate, n["executed_actions"], n["cached_actions"]))
    assert n["executed_actions"] > 0 and n["cached_actions"] == 0, (gate, n)
assert u["core"]["uncached"] is True and w["core"]["uncached"] is False
assert b["executed_actions"] > 0 and b["cached_actions"] == 0, b
mu = u["metadata"]["gate_metadata"]["mutants"]
print("  uncached mutants: executed %d, cached %d" % (mu["executed_actions"], mu["cached_actions"]))
assert mu["executed_actions"] > 0 and mu["cached_actions"] == 0, mu
f = u["metadata"]["gate_metadata"]["symbols"]
print("  uncached facts: executed %d, cached %d" % (f["executed_actions"], f["cached_actions"]))
assert f["executed_actions"] > 0 and f["cached_actions"] == 0, f
# T073: the toolchain gate verified the cached trees in the uncached grade, and only there.
assert u["metadata"]["gate_metadata"]["toolchain"]["verified"] is True, u["metadata"]["gate_metadata"]["toolchain"]
assert w["metadata"]["gate_metadata"]["toolchain"]["verified"] is False
print("  toolchain: verified in the uncached grade, not verified (cached grade) in the warm one")
assert u["core_sha256"] != w["core_sha256"]
EOF4

python3 -I - "$work/warm.verdict.json" "$work/tier-merge.verdict.json" <<'EOF15' || fail "tier merge: wrong mutants gate or verdict"
import json, sys
n, m = (json.load(open(p)) for p in sys.argv[1:])
gn, gm = n["metadata"]["gate_metadata"]["mutants"], m["metadata"]["gate_metadata"]["mutants"]
fm = json.load(open(sys.argv[2].replace(".verdict.json", "/results/mutants.json")))["findings"]
assert n["core"]["inputs"]["tier"] == "nightly" and m["core"]["inputs"]["tier"] == "merge"
assert n["core_sha256"] != m["core_sha256"], "a merge PASS and a nightly PASS have the same core_sha256"
assert set(gn["modules"]) == {"//core:core", "//util:util"} and "tier" not in gn and "deferred" not in gn, gn
assert set(gm["modules"]) == {"//core:core"} and gm["tier"] == "merge" and gm["deferred"] == 1, gm
assert gm["modules"]["//core:core"]["total"] > 0 and gm["modules"]["//core:core"]["survivors"] == [], gm
assert set(gm["targets"]) == {"//core:core"}, gm["targets"]
assert [(f["rule"], f["module"], f["severity"]) for f in fm] == [("mutation-deferred", "//util:util", "info")], fm
an, am = gn["executed_actions"] + gn["cached_actions"], gm["executed_actions"] + gm["cached_actions"]
print("  mutants actions (executed + cached): nightly %d, merge %d; deferred %s" % (an, am, fm[0]["reason"]))
assert 0 < am < an, (am, an)
EOF15

python3 -I - "$work/warm.verdict.json" "$work/witness-na.verdict.json" <<'EOF8' || fail "witness-na: the head gates differ from the grading without --witness"
import json, sys
a, b = (json.load(open(p))["metadata"]["gate_metadata"] for p in sys.argv[1:])
for gate in ("build", "symbols", "mutants", "structure", "mode-divergence"):
    ca = (a[gate]["executed_actions"], a[gate]["cached_actions"])
    cb = (b[gate]["executed_actions"], b[gate]["cached_actions"])
    print("  %-16s executed/cached without --witness %s, with %s" % (gate, ca, cb))
    assert ca == cb, gate
EOF8

# ---------------------------------------------------------------------------------------
# T073: the `toolchain` gate fails. No product can make it fail (canaries/runner.py
# GRADER_INTEGRITY_GATES exempts it from canary coverage because of this step). A scratch clone of
# the gate commit gets one sha256 of llvm.manifest flipped and grades the clean head --uncached: the
# cached tree no longer matches the manifest. Nothing shared is written: the clone lives in $work, the
# fetch step only reads the action cache and the verify step is --no-remote-cache.
# ---------------------------------------------------------------------------------------
step=$((step + 1))
echo "[$step] toolchain mismatch: a scratch gate clone with one llvm.manifest sha256 flipped, --uncached"
mismatch_gate="$work/gate-mismatch"
root_status_before="$(git -C "$root" status --porcelain=v1 --untracked-files=no)"
# The exact commit this script runs from (also on a detached HEAD), copied (no hardlinks) into $work.
{ git init -q -b mismatch "$mismatch_gate" && git -C "$mismatch_gate" fetch -q --no-tags "$root" HEAD &&
  git -C "$mismatch_gate" reset -q --hard FETCH_HEAD; } || fail "toolchain mismatch: copy of the gate commit"
[ "$(git -C "$mismatch_gate" rev-parse HEAD)" = "$(git -C "$root" rev-parse HEAD)" ] || fail "toolchain mismatch: wrong commit"
flipped="$(python3 -I - "$mismatch_gate/toolchains/llvm.manifest" <<'EOF9'
import sys
path = sys.argv[1]
lines = open(path, encoding="utf-8").read().split("\n")
for i, line in enumerate(lines):
    fields = line.split("\t")
    if len(fields) == 5 and fields[0] == "f":
        digest = fields[3]
        fields[3] = digest[:-1] + ("1" if digest[-1] != "1" else "2")
        lines[i] = "\t".join(fields)
        break
open(path, "w", encoding="utf-8").write("\n".join(lines))
print(fields[4])
EOF9
)" || fail "toolchain mismatch: flip"
git -C "$mismatch_gate" commit -q -am "selftest: one llvm.manifest sha256 flipped" || fail "toolchain mismatch: commit"
started="$(now)"
python3 -I -B "$mismatch_gate/gate/rigor" grade --product-repo "$repo" --base "$base" --head "$last_head" \
    --task "$work/task.toml" --product "$mismatch_gate/$product" --work "$work/toolchain-mismatch" \
    --out "$work/toolchain-mismatch.verdict.json" --uncached > "$work/toolchain-mismatch.log" 2>&1
code=$?
echo "  exit $code, $(elapsed "$started")s, flipped: $flipped"
python3 -I - "$work/toolchain-mismatch.verdict.json" "$work/toolchain-mismatch/results/toolchain.json" "$code" "$flipped" <<'EOF10' || { tail -n 30 "$work/toolchain-mismatch.log" >&2; fail "toolchain mismatch: wrong verdict"; }
import json, sys
core = json.load(open(sys.argv[1]))["core"]
result = json.load(open(sys.argv[2]))
code, flipped = int(sys.argv[3]), sys.argv[4]
got = {g["id"]: g["status"] for g in core["gates"]}
print("  " + " ".join("%s=%s" % kv for kv in got.items()) + "  overall=" + core["overall"])
compiling = {"semantic-suppressions", "symbols", "build", "structure", "mode-divergence", "fuzz", "mutants",
             "witness-tests", "mutants-witness"}
assert code == 1 and core["overall"] == "FAIL" and core["uncached"] is True, (code, core["overall"])
assert {g for g, s in got.items() if s == "FAIL"} == {"toolchain"}, got
assert {g for g, s in got.items() if s == "NOT_RUN"} == compiling | {"tests-release", "tests-san"}, got
[item] = [f for f in result["findings"] if f["severity"] == "error"]
assert item["rule"] == "toolchain-mismatch" and item["step"] == "verify", item
assert item["manifest"] == "toolchains/llvm.manifest" and item["first_difference"] == flipped, item
assert item["verifier_exit_code"] == 1, item
print("  toolchain-mismatch: manifest %s, first difference %s, buck2 exit %d" % (item["manifest"], flipped, item["exit_code"]))
EOF10
grep -Eq "^build +not run: gate toolchain is FAIL$" "$work/toolchain-mismatch.log" || fail "toolchain mismatch: no not-run reason in the log"
[ -z "$(find_daemons "$work/toolchain-mismatch")" ] || fail "toolchain mismatch: a process is still running"
[ "$(git -C "$root" status --porcelain=v1 --untracked-files=no)" = "$root_status_before" ] || fail "toolchain mismatch: the gate checkout changed"
echo "  the gate checkout is unchanged and no daemon is left"

# The mutants gate's reuse of unchanged modules (T121): its own script, its own product repo and work dirs.
echo "[mutants-cache] repeat grade, one-module change, survivor on a cache hit (selftest/mutants_cache.sh)"
bash selftest/mutants_cache.sh > "$work/mutants_cache.log" 2>&1 || { tail -n 30 "$work/mutants_cache.log" >&2; fail "mutants cache"; }
cat "$work/mutants_cache.log"

echo "SUMMARY: cold ${cold_secs}s (executed $exec_cold build actions); parallel steps (warm, hostile, uncached, internal, 3 witness, extra-export, fuzz, fuzz corpus, 7 test-author) ${parallel_secs}s"
echo "selftest/grade.sh: all $step steps passed"
