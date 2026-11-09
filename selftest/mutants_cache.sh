#!/usr/bin/env bash
# Self-test of the mutants gate's reuse (T121): the `mutant_run` actions are Buck2 actions, so a grade of unchanged
# modules must be answered by the RE action cache whatever the work dir, the module's position in the grading or the
# chunking; and a cache hit must give the same verdict as the run that filled it (the verdict is read from the cached
# action OUTPUT).
#   (a) the same head graded twice in two work dirs: ZERO mutant_run actions execute, every digest is identical;
#   (b) a head that changes one module (an independent one): only that module's mutant_run actions execute;
#   (c) a head with a surviving mutant, graded twice: the second grade executes nothing and reports the same survivors.
# Needs bash, git, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR (default /var/tmp), removed on exit
# (RIGOR_GRADE_KEEP=1 keeps it).
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TMPDIR="${TMPDIR:-/var/tmp}"
work="$(mktemp -d "$TMPDIR/rigor-mcache.XXXXXX")"
repo="$work/repo"

cleanup() {
  local t
  for t in "$work"/*/tree; do
    [ -f "$t/gate/tools/buck2" ] && (cd "$t" && bash gate/tools/buck2 kill >/dev/null 2>&1)
  done
  if [ "${RIGOR_GRADE_KEEP:-}" = 1 ]; then echo "kept $work"; else rm -rf "$work" 2>/dev/null || { chmod -R u+w "$work"; rm -rf "$work"; }; fi
}
trap cleanup EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }

export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
export GIT_AUTHOR_NAME=selftest GIT_AUTHOR_EMAIL=selftest@example.invalid
export GIT_COMMITTER_NAME=selftest GIT_COMMITTER_EMAIL=selftest@example.invalid

mkdir -p "$repo"
cp -r selftest/grade_product/. "$repo/"
# core and util are coupled (util's tests link core and core's mutants link what util's test links), so a third module
# that nothing else links is added: the canary `new-module` has exactly that (//core:extra) and the policy gets its entry.
(cd "$repo" && bash "$root/canaries/new-module/edit.sh")
mkdir -p "$work/product"
cp products/selftest/product.toml products/selftest/policy.toml "$work/product/"
cp canaries/new-module/expected-tests.json "$work/product/expected-tests.json"
cat >> "$work/product/policy.toml" <<'EOT'

[module."//core:extra"]
level = "L2"
impl = ["core/extra.c"]
allow = []
exports = ["extra_twice"]

[module."//core:extra_test"]
allow = []
exports = ["main"]
EOT
product="$work/product/product.toml"
printf '\n/* selftest nonce %s-%s */\n' "$(date +%s%N)" "$$" >> "$repo/core/core.c"   # the first grade really executes
git -C "$repo" init -q -b main
git -C "$repo" add -A
git -C "$repo" commit -q -m base
base="$(git -C "$repo" rev-parse HEAD)"
printf 'id = "selftest"\nallowed = ["core/**", "util/**", ".buckconfig", "extra/**", "third_party/**"]\n' > "$work/task.toml"

head_of() {  # head_of <name> <edit command run in the repo>: a commit on top of base
  git -C "$repo" checkout -q -f -B "case-$1" "$base"
  git -C "$repo" clean -q -fdx
  (cd "$repo" && eval "$2")
  git -C "$repo" add -A
  git -C "$repo" commit -q -m "$1"
  git -C "$repo" rev-parse HEAD
}

grade() {  # grade <name> <head>: its own work dir; the exit code is not judged here (c fails the mutants gate on purpose)
  python3 -I -B gate/rigor grade --product-repo "$repo" --base "$base" --head "$2" --task "$work/task.toml" \
      --product "$product" --work "$work/$1" --out "$work/$1.verdict.json" > "$work/$1.log" 2>&1
  echo "  graded $1 (exit $?)"
}

# ran <name>: JSON {"<mutant_run identity>": [executor, digest]} of every mutant_run action of that grading
ran() {
  python3 -I - "$work/$1/tree" <<'PY'
import glob, json, subprocess, sys
tree = sys.argv[1]
out = {}
for log in sorted(glob.glob(tree + "/buck-out/v2/log/*_build_*_events.pb.zst")):
    done = subprocess.run(["bash", "gate/tools/buck2", "log", "what-ran", "--filter-category", "mutant_run", "--format", "json", log],
                          cwd=tree, capture_output=True, check=True)
    for line in done.stdout.decode().splitlines():
        item = json.loads(line)
        out[item["identity"]] = [item["reproducer"]["executor"], item["reproducer"]["details"]["digest"]]
print(json.dumps(out))
PY
}

mutants_findings() {  # the mutants gate's findings, canonical
  python3 -I -c 'import json,sys; print(json.dumps(sorted(json.dumps(f, sort_keys=True) for f in json.load(open(sys.argv[1]))["findings"])))' "$work/$1/results/mutants.json"
}

# (a) same head, two work dirs
echo "[a] the same head in two work dirs"
grade a1 "$base"; grade a2 "$base"
ran a1 > "$work/a1.ran"; ran a2 > "$work/a2.ran"
python3 -I - "$work/a1.ran" "$work/a2.ran" <<'PY' || fail "(a) a repeat grade re-executed mutant_run actions, or their digests differ"
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
assert a and set(a) == set(b), (len(a), len(b))
assert all(v[0] == "Cache" for v in b.values()), {k: v[0] for k, v in b.items() if v[0] != "Cache"}
assert all(a[k][1] == b[k][1] for k in a), [k for k in a if a[k][1] != b[k][1]]
print("  %d mutant_run actions, 0 executed in the repeat, digests identical" % len(b))
PY

# (b) one module changes: only its mutant_run actions execute
echo "[b] a change to the independent module only"
# a change of the object code, not of a comment: a comment would give the same objects and every action would stay cached
h_extra="$(head_of extra "sed -i 's/return a + a;/return 2 * a;/' core/extra.c")"
git -C "$repo" diff --quiet "$base" "$h_extra" -- core/extra.c && fail "(b) the edit changed nothing"
grade b "$h_extra"
ran b > "$work/b.ran"
python3 -I - "$work/b.ran" <<'PY' || fail "(b) a mutant_run action of an unchanged module executed, or the changed module's did not"
import json, sys
b = json.load(open(sys.argv[1]))
executed = {k for k, v in b.items() if v[0] != "Cache"}
own = [k for k in b if "_core_extra_" in k]
others = [k for k in b if "_core_extra_" not in k]
assert own and others, (len(own), len(others))
assert not executed & set(others), sorted(executed & set(others))
assert executed and executed <= set(own), sorted(executed)
print("  executed %d of %d mutant_run actions of the changed module, 0 of %d of the others" % (len(executed), len(own), len(others)))
PY

# (c) a surviving mutant stays a survivor on a cache hit
echo "[c] a surviving mutant, graded twice"
h_weak="$(head_of weak "sed -i '/core_sign(0), 0/d' core/core_test.c")"
grade c1 "$h_weak"; grade c2 "$h_weak"
ran c1 > "$work/c1.ran"; ran c2 > "$work/c2.ran"
python3 -I - "$work/c2.ran" <<'PY' || fail "(c) the repeat grade executed mutant_run actions"
import json, sys
c = json.load(open(sys.argv[1]))
assert c and all(v[0] == "Cache" for v in c.values()), {k: v[0] for k, v in c.items() if v[0] != "Cache"}
print("  repeat: %d mutant_run actions, all answered by the cache" % len(c))
PY
f1="$(mutants_findings c1)"; f2="$(mutants_findings c2)"
python3 -I - "$f1" "$f2" <<'PY' || fail "(c) the cached grade did not report the same surviving mutants"
import json, sys
a, b = json.loads(sys.argv[1]), json.loads(sys.argv[2])
rules = {json.loads(f)["rule"] for f in a}
assert "survived-mutant" in rules, rules
assert a == b, "findings differ"
print("  %d findings, identical on the cache hit, rules %s" % (len(a), sorted(rules)))
PY
echo "mutants cache selftest: PASS"
