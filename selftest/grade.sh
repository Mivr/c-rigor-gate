#!/usr/bin/env bash
# Self-test of `rigor grade` (T005): builds a throwaway product repo from selftest/grade_product,
# grades one clean change and a set of red changes end to end (real clone, Buck2 on RE), and
# checks that every red change fails in exactly the gates that should catch it.
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
  for t in "$work"/*/tree; do
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
allowed = ["core/**", "util/**", ".buckconfig"]
EOF

# ---------------------------------------------------------------------------------------
# Edits: each runs inside $repo on top of base and changes one thing.
# ---------------------------------------------------------------------------------------
edit_clean() { printf '\n/* clean change */\n' >> core/core.c; }
edit_outside_contract() { mkdir -p docs; echo "notes" > docs/notes.txt; }
edit_nolint() { printf '\n/* NOLINT */\n' >> core/core.c; }
edit_buckconfig_hidden() {  # a -Werror-disabling .buckconfig that the suppression scan cannot see
  printf '[cxx]\n  cflags = -W\\\nno-error\n' > .buckconfig
  sed -i 's/^int core_add(int a, int b) { return a + b; }/int core_add(int a, int b) { int unused_value = 3; return a + b; }/' core/core.c
}
edit_buckconfig_plain() {  # same, spelled out: the suppression scan sees it too
  printf '[cxx]\n  cflags = -Wno-error\n' > .buckconfig
  sed -i 's/^int core_add(int a, int b) { return a + b; }/int core_add(int a, int b) { int unused_value = 3; return a + b; }/' core/core.c
}
edit_product_buck2() {
  mkdir -p tools
  printf '#!/bin/sh\necho ran > "%s/tools-buck2-ran"\nexit 1\n' "$work" > tools/buck2
  chmod +x tools/buck2
}
edit_failing_test() { sed -i 's/return a + b; }$/return a + b + 1; }/' core/core.c; }
edit_removed_test() {
  python3 - <<'EOF'
import re
p = "util/util_test.c"
s = open(p).read()
s = re.sub(r"static void t_sum\(ctest_t \*t\) \{.*?\n\}\n\n", "", s, flags=re.S)
s = s.replace('{ "sum", t_sum }, ', "")
open(p, "w").write(s)
EOF
}
edit_deleted_target() { sed -i '/^c_test(name = "util_test"/d' util/BUCK; }
edit_heap_overflow() { sed -i 's/^    return ramp;/    ramp[count] = 0;\n    return ramp;/' util/util.c; }

# ---------------------------------------------------------------------------------------
# check_verdict <verdict.json> <expected failing gates, comma separated or empty> <exit code>
# ---------------------------------------------------------------------------------------
check_verdict() {
  python3 -I - "$1" "$2" "$3" <<'EOF'
import json, sys
path, expected, code = sys.argv[1], set(filter(None, sys.argv[2].split(","))), int(sys.argv[3])
core = json.load(open(path))["core"]
got = {g["id"]: g["status"] for g in core["gates"]}
bad = {g for g, s in got.items() if s != "PASS"}
want_code = 1 if expected else 0
print("  " + " ".join("%s=%s" % (g, s) for g, s in got.items()) + "  overall=" + core["overall"])
ok = bad == expected and code == want_code and (core["overall"] == "PASS") == (not expected)
if not ok:
    print("  EXPECTED failing gates %s (exit %d), got %s (exit %d)" % (sorted(expected), want_code, sorted(bad), code))
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
  check_verdict "$verdict" "$expected" "$code" || { tail -n 30 "$work/$name.log" >&2; fail "$name"; }
  [ -z "$(find_daemons "$work/$name")" ] || fail "$name: a process is still running in the grading tree"
  last_head="$head"
}

# 1. clean change, cold (fresh nonce: everything executes), then warm (same head, nothing executes)
run_case clean "" ; cold_secs="$secs"
cold_verdict="$verdict"
exec_cold="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]["build"]["executed_actions"])' "$cold_verdict")"
[ "$exec_cold" -gt 0 ] || fail "cold run executed no actions: the nonce did not reach the build"

step=$((step + 1))
echo "[$step] clean, same head again in a fresh work dir (warm), signed"
ssh-keygen -q -t ed25519 -N "" -C selftest -f "$work/key" >/dev/null || fail "ssh-keygen"
started="$(now)"
"${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
    --product "$product" --work "$work/warm" --out "$work/warm.verdict.json" --sign-key "$work/key" \
    > "$work/warm.log" 2>&1
code=$?
warm_secs="$(elapsed "$started")"
echo "  exit $code, ${warm_secs}s"
check_verdict "$work/warm.verdict.json" "" "$code" || { tail -n 30 "$work/warm.log" >&2; fail "warm"; }
exec_warm="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]["build"]["executed_actions"])' "$work/warm.verdict.json")"
echo "  build actions executed: cold $exec_cold, warm $exec_warm"
[ "$exec_warm" = 0 ] || fail "warm run executed $exec_warm build actions"
sha_cold="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_sha256"])' "$cold_verdict")"
sha_warm="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_sha256"])' "$work/warm.verdict.json")"
[ "$sha_cold" = "$sha_warm" ] || fail "core_sha256 differs between two runs of the same inputs"
echo "  core_sha256 identical: $sha_warm"
ssh-keygen -Y check-novalidate -n c-rigor-gate-verdict -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
  || fail "verdict.json.sig does not verify"
ssh-keygen -Y check-novalidate -n c-rigor-gate -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
  && fail "verdict signature verifies under the wrong namespace"
echo "  signature verifies (namespace c-rigor-gate-verdict only)"

# 2. red cases: each must fail in exactly these gates
run_case outside-contract contract
run_case nolint suppressions
run_case buckconfig-hidden build
run_case buckconfig-plain suppressions,build
run_case product-buck2 contract
[ ! -e "$work/tools-buck2-ran" ] || fail "the product's tools/buck2 was executed"
run_case failing-test tests-release,tests-san
run_case removed-test tests-release,tests-san
run_case deleted-target tests-release,tests-san
run_case heap-overflow tests-san

# 3. an internal error (unreadable contract) is exit 2 and a FAIL verdict
step=$((step + 1))
echo "[$step] internal-error"
"${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/no-such-task.toml" \
    --product "$product" --work "$work/internal" --out "$work/internal.verdict.json" > "$work/internal.log" 2>&1
code=$?
[ "$code" = 2 ] || fail "internal-error: exit $code instead of 2"
python3 -I - "$work/internal.verdict.json" <<'EOF' || fail "internal-error: verdict"
import json, sys
core = json.load(open(sys.argv[1]))["core"]
got = {g["id"]: g["status"] for g in core["gates"]}
print("  " + " ".join("%s=%s" % kv for kv in got.items()))
assert core["overall"] == "FAIL" and got["contract"] == "FAIL" and got["build"] == "NOT_RUN", got
EOF
[ -z "$(find_daemons "$work/internal")" ] || fail "internal-error: a process is still running"

echo "SUMMARY: cold ${cold_secs}s (executed $exec_cold build actions), warm ${warm_secs}s (executed $exec_warm)"
echo "selftest/grade.sh: all $step steps passed"
