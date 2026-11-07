#!/usr/bin/env bash
# Validate a task branch the cheap way (T044): run exactly the selftests that tools/affected.py selects for the
# branch's changes against main, and print one summary table. Run it in the orchestrator's val worktree, already
# merged with main. It never merges, pushes, fetches, or reads agent output.
#
#   tools/validate.sh [--dry-run] BRANCH        BRANCH is any revision (the val worktree's HEAD is fine)
#
# Logs: $TMPDIR/validate/<selftest>.log (TMPDIR defaults to /var/tmp). Exit 0 only if every selftest exited 0.
# Needs bash, git, python3 (stdlib). See docs/validation.md.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root" || exit 2
export TMPDIR="${TMPDIR:-/var/tmp}"

dry=0
branch=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry=1 ;;
    -*) echo "usage: tools/validate.sh [--dry-run] BRANCH" >&2; exit 2 ;;
    *) [ -z "$branch" ] || { echo "usage: tools/validate.sh [--dry-run] BRANCH" >&2; exit 2; }; branch="$arg" ;;
  esac
done
[ -n "$branch" ] || { echo "usage: tools/validate.sh [--dry-run] BRANCH" >&2; exit 2; }

head="$(git rev-parse --verify --quiet "$branch^{commit}")" || { echo "validate.sh: no such revision: $branch" >&2; exit 2; }
base="$(git merge-base main "$head")" || { echo "validate.sh: no merge base with main" >&2; exit 2; }
selected="$(python3 -I tools/affected.py "$base" "$head")" || { echo "validate.sh: tools/affected.py failed" >&2; exit 2; }

logdir="$TMPDIR/validate"

# The command of each selftest.
command_of() {
  case "$1" in
    gate) echo "selftest/gate.sh" ;;
    canaries) echo "selftest/canaries.sh --jobs 8" ;;
    tripwires) echo "selftest/tripwires.sh --jobs 5" ;;
    trajectory_real) echo "gate/tests/trajectory_real.sh" ;;
    grade|mutate|structure|product_checks|toolchain|ctest|fuzz|third_party|perf) echo "selftest/$1.sh" ;;
    *) echo "validate.sh: unknown selftest $1" >&2; return 1 ;;
  esac
}

# Lanes run in parallel with each other. Selftests that build in THIS project root share one Buck2 daemon and read
# `buck2 log what-ran` (the last command of the root), so they run one after another in lane "root". grade and
# canaries and tripwires work in their own clones; gate and trajectory_real do not use Buck2.
have() { printf '%s\n' "$selected" | grep -qx "$1"; }
ROOT_ORDER=(product_checks ctest perf toolchain fuzz structure mutate third_party)
root_lane=()
for n in "${ROOT_ORDER[@]}"; do have "$n" && root_lane+=("$n"); done
other_lanes=()
for n in gate grade canaries tripwires trajectory_real; do have "$n" && other_lanes+=("$n"); done

if [ "$dry" = 1 ]; then
  echo "validate (dry run): branch $branch = ${head:0:12}, merge base with main ${base:0:12}"
  echo "selected: $(printf '%s\n' "$selected" | tr '\n' ' ')"
  echo "logs in: $logdir/<selftest>.log"
  [ "${#root_lane[@]}" -eq 0 ] || echo "lane root (in order): ${root_lane[*]}"
  for n in "${other_lanes[@]}"; do echo "lane $n"; done
  while IFS= read -r n; do echo "  $n: $(command_of "$n")"; done <<<"$selected"
  exit 0
fi

mkdir -p "$logdir" || exit 2
rm -f "$logdir"/*.log "$logdir"/*.result

run_one() {
  local name="$1" cmd start code
  cmd="$(command_of "$name")" || return 1
  start=$SECONDS
  $cmd > "$logdir/$name.log" 2>&1
  code=$?
  echo "$code $((SECONDS - start))" > "$logdir/$name.result"
}

pids=()
for n in "${other_lanes[@]}"; do run_one "$n" & pids+=($!); done
if [ "${#root_lane[@]}" -gt 0 ]; then
  ( for n in "${root_lane[@]}"; do run_one "$n"; done ) &
  pids+=($!)
fi
for p in "${pids[@]}"; do wait "$p"; done

status=0
printf '%-16s %5s %7s  %s\n' selftest exit seconds "last line"
while IFS= read -r n; do
  if [ -r "$logdir/$n.result" ]; then
    read -r code secs < "$logdir/$n.result"
  else
    code="?"; secs="?"
  fi
  last="$(grep -v '^[[:space:]]*$' "$logdir/$n.log" 2>/dev/null | tail -n 1 | cut -c1-120)"
  printf '%-16s %5s %7s  %s\n' "$n" "$code" "$secs" "$last"
  [ "$code" = 0 ] || status=1
done <<<"$selected"
[ "$status" = 0 ] && echo "validate: all selected selftests passed" || echo "validate: FAILED (logs in $logdir)"
exit "$status"
