#!/usr/bin/env bash
# Self-test of `rigor grade` (T005): builds a throwaway product repo from selftest/grade_product,
# grades one clean change end to end (real clone, Buck2 on RE) cold, warm, hostile, uncached and with an internal error;
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
want_not_run = ({"tests-release", "tests-san", "semantic-suppressions", "symbols", "structure", "mode-divergence"}
                if "build" in expected else set())
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
this script keeps the property steps: cold, warm (+ signature), hostile environment, --uncached, internal error
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

names=(warm hostile uncached internal)
labels=("clean, same head again in a fresh work dir (warm), signed" "hostile inherited environment" "clean, --uncached" "internal-error")
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
assert u["core_sha256"] != w["core_sha256"]
EOF4

echo "SUMMARY: cold ${cold_secs}s (executed $exec_cold build actions); parallel steps (warm, hostile, uncached, internal) ${parallel_secs}s"
echo "selftest/grade.sh: all $step steps passed"
