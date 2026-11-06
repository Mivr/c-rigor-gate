#!/bin/sh
# Run the rigor kernel's own tests. Exit 0 only if every test passes.
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"

# Only /var/tmp is writable for agents; keep test scratch space there.
export TMPDIR="${TMPDIR:-/var/tmp}"

# rigor needs Python 3.12 (tomllib, current argparse behaviour).
python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' ||
    { echo "selftest/gate.sh: Python 3.12 or newer is required" >&2; exit 2; }

# -I: no user site or PYTHON* variables; -B: do not write .pyc files into the repo.
python3 -I -B -m unittest discover -s gate/tests -t gate
echo "selftest/gate.sh: all gate tests passed"
