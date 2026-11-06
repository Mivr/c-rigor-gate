#!/usr/bin/env bash
# The canary pack (T018, backlog B6): every known cheat must still be red in the assembled gate.
# Each canaries/<id>/ is graded through `rigor grade` (real clone, Buck2 on RE) and must FAIL in exactly
# the gate and rule named in its expect.json. Needs bash, git, python3 (stdlib) and tools/buck2.
# Usage: selftest/canaries.sh [--jobs N] [--only ID]... [--uncached ID] [--keep]
set -uo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
export TMPDIR="${TMPDIR:-/var/tmp}"
started="$(date +%s)"
python3 -I -B canaries/runner.py "$@"
code=$?
echo "selftest/canaries.sh: exit $code after $(( $(date +%s) - started ))s"
exit "$code"
