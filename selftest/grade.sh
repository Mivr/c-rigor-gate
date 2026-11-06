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
allowed = ["core/**", "util/**", ".buckconfig", "extra/**", "third_party/**"]
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
# Product checks (T007). Each is spelled so that the text scan of `suppressions` cannot see it.
edit_kills() {  # symbols: core references kill (never called)
  printf '\nint kill(int pid, int sig);\nint core_stop(int pid);\nint core_stop(int pid) { return kill(pid, 0); }\n' >> core/core.c
}
edit_spliced_optnone() {  # semantic-suppressions: attribute built by pasting, #line spliced
  printf '\n#define GLUE(a, b) a##b\nint core_slow(int a);\n__attribute__((GLUE(opt, none))) int core_slow(int a) { return a; }\n#li\\\nne 1 "fake.c"\n' >> core/core.c
}
edit_raw_rule() {  # buckfiles: a raw rule beside the macros (it is never built)
  printf '\nnative.cxx_library(name = "raw", srcs = ["core.c"])\n' >> core/BUCK
}
# Layout coverage (T013, B14): product code the layout leaves out is a finding, never silence.
edit_ungraded_module() {  # a module directory the layout does not list
  mkdir -p extra
  printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "extra", srcs = ["extra.c"], visibility = ["PUBLIC"])\n' > extra/BUCK
  printf 'int extra_one(void) { return 1; }\n' > extra/extra.c
}
edit_excluded_code() {  # a C file under a path the (variant) product.toml excludes as "docs"
  mkdir -p core/docs
  printf 'int hidden_one(void) { return 1; }\n' > core/docs/hidden.c
}
edit_stale_include() { printf '\n/* stale include case */\n' >> core/core.c; }
edit_third_party_copy() {  # a vendored copy of a library inside the product: gate//third_party is the only source
  mkdir -p third_party/mini
  printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "mini", srcs = ["mini.c"], visibility = ["PUBLIC"])\n' > third_party/mini/BUCK
  printf 'int mini_one(void) { return 1; }\n' > third_party/mini/mini.c
}
edit_case_collision() {  # two paths that differ only in letter case
  printf 'int case_one(void) { return 1; }\n' > core/Twin.c
  printf 'int case_two(void) { return 2; }\n' > core/twin.c
}
# Mutation testing (T008).
edit_weak_test() {  # a check is gone: the mutants around zero in core_sign survive
  sed -i '/core_sign(0), 0/d' core/core_test.c
}
edit_hollow_module() {  # all logic moves into the header: the source has nothing left to mutate
  cat > core/core.h <<'EOT'
#ifndef CORE_H
#define CORE_H

extern const int core_marker;
static inline int core_add(int a, int b) { return a + b; }
static inline int core_sign(int value) {
    if (value < 0) {
        return -1;
    }
    if (value > 0) {
        return 1;
    }
    return 0;
}

#endif
EOT
  printf '#include "core.h"\n\nconst int core_marker = 1;\n' > core/core.c
}
edit_unviable_shape() {  # most mutants of this function trip -Werror (255 -> 256 in an unsigned char)
  sed -i 's/^#endif/unsigned core_sum_ff(void);\n\n#endif/' core/core.h
  { printf '\nunsigned core_sum_ff(void) {\n    static const unsigned char table[32] = {'
    for i in $(seq 1 32); do printf '255, '; done
    printf '};\n    unsigned total = 0;\n    for (unsigned i = 0; i < 32; i++) {\n        total += table[i];\n    }\n    return total;\n}\n'
  } >> core/core.c
  sed -i 's/^    CHECK_EQ_I64(t, core_add(-4, 4), 0);/&\n    CHECK_EQ_I64(t, core_sum_ff(), 8160);/' core/core_test.c
}
edit_new_module() {  # a library the policy has never heard of: no level, so the gate cannot decide how hard to test it
  cat >> core/BUCK <<'EOT'

c_library(name = "extra", srcs = ["extra.c"], headers = ["extra.h"], visibility = ["PUBLIC"])

c_test(name = "extra_test", srcs = ["extra_test.c"], deps = [":extra"])
EOT
  printf '#ifndef EXTRA_H\n#define EXTRA_H\nint extra_twice(int a);\n#endif\n' > core/extra.h
  printf '#include "extra.h"\n\nint extra_twice(int a) { return a + a; }\n' > core/extra.c
  printf '#include "ctest/ctest.h"\n#include "extra.h"\n\nstatic void t_twice(ctest_t *t) {\n    CHECK_EQ_I64(t, extra_twice(4), 8);\n}\n\nCTEST_SUITE("extra", { "twice", t_twice })\n' > core/extra_test.c
}
edit_heap_overflow() { sed -i 's/^    return ramp;/    ramp[count] = 0;\n    return ramp;/' util/util.c; }

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
# Mutation testing needs a clean tree and green tests: it is NOT_RUN after any of these failed.
want_not_run = {"tests-release", "tests-san", "semantic-suppressions", "symbols"} if "build" in expected else set()
if expected & {"assemble", "buckfiles", "build", "tests-release", "tests-san"}:
    want_not_run.add("mutants")
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
exec_facts_warm="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]["symbols"]["executed_actions"])' "$work/warm.verdict.json")"
[ "$exec_facts_warm" = 0 ] || fail "warm run executed $exec_facts_warm facts actions"
exec_mut_warm="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["gate_metadata"]["mutants"]["executed_actions"])' "$work/warm.verdict.json")"
[ "$exec_mut_warm" = 0 ] || fail "warm run executed $exec_mut_warm mutants actions"
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
sha_cold="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_sha256"])' "$cold_verdict")"
sha_warm="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_sha256"])' "$work/warm.verdict.json")"
[ "$sha_cold" = "$sha_warm" ] || fail "core_sha256 differs between two runs of the same inputs"
echo "  core_sha256 identical: $sha_warm"
ssh-keygen -Y check-novalidate -n c-rigor-gate-verdict -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
  || fail "verdict.json.sig does not verify"
ssh-keygen -Y check-novalidate -n c-rigor-gate -s "$work/warm.verdict.json.sig" < "$work/warm.verdict.json" >/dev/null 2>&1 \
  && fail "verdict signature verifies under the wrong namespace"
echo "  signature verifies (namespace c-rigor-gate-verdict only)"

# 1b. the pipeline ignores the inherited environment: hostile user config in HOME, BUCK2_* and
#     LD_PRELOAD in the parent must change nothing, down to core_sha256
step=$((step + 1))
echo "[$step] hostile inherited environment"
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
sha_hostile="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["core_sha256"])' "$work/hostile.verdict.json")"
[ "$sha_hostile" = "$sha_cold" ] || fail "core_sha256 changed under a hostile environment"
echo "  core_sha256 identical to the clean run"
[ -z "$(find_daemons "$work/hostile")" ] || fail "hostile: a process is still running"

# 1c. --uncached: every action really runs on a worker, and the verdict says so
step=$((step + 1))
echo "[$step] clean, --uncached"
started="$(now)"
"${rigor[@]}" grade --product-repo "$repo" --base "$base" --head "$last_head" --task "$work/task.toml" \
    --product "$product" --work "$work/uncached" --out "$work/uncached.verdict.json" --uncached \
    > "$work/uncached.log" 2>&1
code=$?
uncached_secs="$(elapsed "$started")"
echo "  exit $code, ${uncached_secs}s"
check_verdict "$work/uncached.verdict.json" "" "$code" "$work/uncached" || { tail -n 30 "$work/uncached.log" >&2; fail "uncached"; }
python3 -I - "$work/uncached.verdict.json" "$work/warm.verdict.json" <<'EOF' || fail "uncached: wrong counts or flag"
import json, sys
u, w = (json.load(open(p)) for p in sys.argv[1:])
b = u["metadata"]["gate_metadata"]["build"]
print("  uncached: executed %d, cached %d" % (b["executed_actions"], b["cached_actions"]))
assert u["core"]["uncached"] is True and w["core"]["uncached"] is False
assert b["executed_actions"] > 0 and b["cached_actions"] == 0, b
mu = u["metadata"]["gate_metadata"]["mutants"]
print("  uncached mutants: executed %d, cached %d" % (mu["executed_actions"], mu["cached_actions"]))
assert mu["executed_actions"] > 0 and mu["cached_actions"] == 0, mu
f = u["metadata"]["gate_metadata"]["symbols"]
print("  uncached facts: executed %d, cached %d" % (f["executed_actions"], f["cached_actions"]))
assert f["executed_actions"] > 0 and f["cached_actions"] == 0, f
assert u["core_sha256"] != w["core_sha256"]
EOF
[ -z "$(find_daemons "$work/uncached")" ] || fail "uncached: a process is still running"

# 2. red cases: each must fail in exactly these gates
run_case outside-contract contract:outside-allowed
run_case nolint suppressions:forbidden-pattern
run_case buckconfig-hidden build:build-failed
grep -q 'unused-variable' "$work/buckconfig-hidden/results/build.json" || fail "buckconfig-hidden: the build did not fail on the warning"
run_case buckconfig-plain suppressions:forbidden-pattern,build:build-failed
run_case product-buck2 contract:outside-allowed
[ ! -e "$work/tools-buck2-ran" ] || fail "the product's tools/buck2 was executed"
run_case failing-test tests-release:test-not-pass,tests-san:test-not-pass
run_case removed-test tests-release:missing-test,tests-san:missing-test
run_case deleted-target tests-release:missing-test,tests-san:missing-test,symbols:policy-module-without-facts
run_case heap-overflow tests-san:test-not-pass
run_case kills symbols:denied-symbol,mutants:survived-mutant   # (the untested core_stop is a survivor too)
run_case spliced-optnone semantic-suppressions:forbidden-attribute,semantic-suppressions:line-directive
run_case raw-rule buckfiles:bad-call
# Mutation testing (T008): each of these must be caught by `mutants` alone (or with the gate named beside it).
run_case weak-test mutants:survived-mutant
run_case hollow-module mutants:no-mutants,mutants:unmutated-function
run_case unviable-shape mutants:unviable-ratio
run_case new-module symbols:module-not-in-policy,mutants:level-missing

# Layout coverage: the product.toml variants live beside copies of the policy and expected tests.
for variant in excl stale; do
  mkdir -p "$work/prod-$variant"
  cp products/selftest/policy.toml products/selftest/expected-tests.json "$work/prod-$variant/"
done
sed 's|^exclude = \[\]|exclude = ["core/docs/**"]|' products/selftest/product.toml > "$work/prod-excl/product.toml"
sed 's|^include = \["core/\*\*",|include = ["gone/**", "core/**",|' products/selftest/product.toml > "$work/prod-stale/product.toml"
grep -q 'core/docs' "$work/prod-excl/product.toml" && grep -q 'gone/' "$work/prod-stale/product.toml" || fail "product.toml variants"
run_case ungraded-module buckfiles:ungraded-path
run_case excluded-code buckfiles:excluded-code --product "$work/prod-excl/product.toml"
run_case stale-include buckfiles:stale-include --product "$work/prod-stale/product.toml"
run_case third-party-copy buckfiles:ignored-code
run_case case-collision buckfiles:case-collision

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

echo "SUMMARY: uncached ${uncached_secs}s; cold ${cold_secs}s (executed $exec_cold build actions), warm ${warm_secs}s (executed $exec_warm)"
echo "selftest/grade.sh: all $step steps passed"
