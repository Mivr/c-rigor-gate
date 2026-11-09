#!/usr/bin/env bash
# Self-test of the lane entry point (T123): `tools/mutants` builds the grade's own mutant actions, so after a lane
# measured a module the grade of the same head executes ZERO mutant_run actions for it, with identical verdicts.
#   (a) a head that changes the independent module //core:extra (fresh code every run, so the lane really executes):
#       `tools/mutants //core:extra` executes mutant actions, prints a table, exit 0, and writes nothing in the repo;
#   (b) `rigor grade` of the same head: every mutant_run action of //core:extra is answered by the cache, and its
#       report and verdict counts equal the lane's;
#   (c) a module that is not mutated is refused (exit 2).
# Needs bash, git, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR (default /var/tmp), removed on exit
# (RIGOR_GRADE_KEEP=1 keeps it).
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TMPDIR="${TMPDIR:-/var/tmp}"
work="$(mktemp -d "$TMPDIR/rigor-lane.XXXXXX")"
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


salt=$((RANDOM * 32768 + RANDOM))
h_extra="$(head_of extra "sed -i 's/return a + a;/return a + a + (a > 1000000 ? $salt : 0);/' core/extra.c")"
git -C "$repo" diff --quiet "$base" "$h_extra" -- core/extra.c && fail "the edit changed nothing"
git -C "$repo" checkout -q -f "$h_extra"

echo "[a] the lane command on //core:extra"
status_before="$(git -C "$repo" status --porcelain --ignored)"
bash tools/mutants //core:extra --product "$product" --repo "$repo" --work "$work/lane" > "$work/lane.out" 2> "$work/lane.err"
code=$?
[ "$code" = 0 ] || { cat "$work/lane.out" "$work/lane.err" >&2; fail "(a) the lane command exited $code"; }
[ "$status_before" = "$(git -C "$repo" status --porcelain --ignored)" ] || fail "(a) the lane command changed the product checkout"
python3 -I - "$work/lane.out" <<'PY' || fail "(a) no mutant table or no executed actions"
import re, sys
text = open(sys.argv[1]).read()
rows = [l for l in text.splitlines() if re.match(r"(killed-\w+|survived|unviable|unrun|equivalent|duplicate)\s", l)]
m = re.search(r"mutant actions: (\d+) executed", text)
assert rows and m and int(m.group(1)) > 0, text
assert "verdict at //core:extra L2: PASS" in text, text
print("  %d mutants listed, %s mutant actions executed" % (len(rows), m.group(1)))
PY

echo "[b] the grade of the same head"
grade g "$h_extra"
ran g > "$work/g.ran"
python3 -I - "$work/g.ran" <<'PY' || fail "(b) the grade executed a mutant_run action of //core:extra"
import json, sys
g = json.load(open(sys.argv[1]))
own = {k: v for k, v in g.items() if "_core_extra_" in k}
assert own, sorted(g)
assert all(v[0] == "Cache" for v in own.values()), {k: v[0] for k, v in own.items() if v[0] != "Cache"}
print("  %d mutant_run actions of //core:extra, 0 executed by the grade" % len(own))
PY
python3 -I - "$work/lane/mutants-reports" "$work/g/mutants-reports" "$work/g/results/mutants.json" "$work/lane.out" <<'PY' || fail "(b) the lane's verdicts differ from the grade's"
import glob, json, sys
def label_of(path):
    return json.load(open(path))["label"]
def reports(d):
    return {json.load(open(p))["label"].split(":")[-1]: open(p, "rb").read() for p in sorted(glob.glob(d + "/*.json"))}
lane, grade = reports(sys.argv[1]), reports(sys.argv[2])
key = [k for k in lane if "core_extra" in k]
assert len(key) == 1 and key[0] in grade, (sorted(lane), sorted(grade))
assert lane[key[0]] == grade[key[0]], "the reports differ"
summary = json.load(open(sys.argv[3]))["metadata"]["modules"]["//core:extra"]["verdicts"]
rows = [l.split()[0] for l in open(sys.argv[4]).read().splitlines() if l.split() and l.split()[0] in summary]
counted = {k: rows.count(k) for k in summary if rows.count(k)}
assert counted == {k: v for k, v in summary.items() if v}, (counted, summary)
print("  the report is byte-identical and the verdict counts are the grade's: %s" % counted)
PY

echo "[c] a module that is not mutated"
bash tools/mutants //core:nothing --product "$product" --repo "$repo" --work "$work/lane2" > "$work/c.out" 2> "$work/c.err"
[ "$?" = 2 ] || fail "(c) expected exit 2"
grep -q "not a mutated module" "$work/c.err" || fail "(c) no explanation"
echo "lane mutants cache selftest: PASS"
