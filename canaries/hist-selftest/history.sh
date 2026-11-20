# The fixture history of the historical canary hist-selftest (T2G8): a tiny deterministic repository, `bash history.sh DIR`.
#   c0  the shared base product with two defects (core_add returns a + b + 1; util_make_ramp is off by one)
#   c1  the fix of both defects (the "fix commit"; the canary re-introduces the core_add hunk only)
#   c2  a later commit (the "base" of the canary: it has everything the grader needs; the fix is in its history)
# Dates, names and messages are fixed, so the commit ids in pin.toml are reproducible; the runner checks them.
set -eu
dir="$1"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GIT_AUTHOR_NAME=fixture GIT_AUTHOR_EMAIL=fixture@example.invalid
export GIT_COMMITTER_NAME=fixture GIT_COMMITTER_EMAIL=fixture@example.invalid
mkdir -p "$dir"
cp -r "$here/../_base/product/." "$dir/"
cd "$dir"
git init -q -b main
commit() {
  export GIT_AUTHOR_DATE="2026-01-0$1T12:00:00Z" GIT_COMMITTER_DATE="2026-01-0$1T12:00:00Z"
  git add -A
  git commit -q -m "$2"
}
sed -i 's/return a + b; }$/return a + b + 1; }/' core/core.c
sed -i 's/ramp\[i\] = (int)i;/ramp[i] = (int)i + 1;/' util/util.c
commit 1 "c0: core_add and util_make_ramp are wrong"
sed -i 's/return a + b + 1; }$/return a + b; }/' core/core.c
sed -i 's/ramp\[i\] = (int)i + 1;/ramp[i] = (int)i;/' util/util.c
commit 2 "c1: fix core_add and util_make_ramp"
printf 'later work\n' > NOTES.txt
commit 3 "c2: later work"
