#!/usr/bin/env bash
# The tripwire pack (T086, backlog B6): honest products with an obligation no code can meet; every one must stay red.
# Same runner as selftest/canaries.sh over tripwires/. One tripwire is graded --uncached (rotated by day).
# A tripwire that goes green means the gate it names is blind. See docs/tripwires.md.
# Usage: selftest/tripwires.sh [--jobs N] [--only ID]... [--uncached ID] [--keep]
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TMPDIR="${TMPDIR:-/var/tmp}"
started="$(date +%s)"
python3 -I -B canaries/runner.py --root tripwires "$@"
code=$?
echo "selftest/tripwires.sh: exit $code after $(( $(date +%s) - started ))s"
exit "$code"
