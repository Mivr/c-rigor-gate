"""Facts of a gate-owned third-party library: its exported symbols, computed from the objects.

Writes the same JSON file `rigor facts` reads for every module (see gate/rigor_lib/facts_data.py),
with kind `c_third_party` and nothing but symbols: the library is trusted, not scanned. The symbol
lists come from the pinned `llvm-nm`; nobody writes them by hand.

Usage: tp_facts.py --label L --nm NM --out F --unit NAME OBJECT [--unit NAME OBJECT ...]
"""

import argparse
import json
import subprocess
import sys

UNDEFINED_TYPES = ("U", "w", "v")
WEAK_DEFINED_TYPES = ("W", "V", "i", "I", "u")


def symbols(nm, path):
    done = subprocess.run([nm, "-g", "--format=posix", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise SystemExit("tp_facts: nm failed on %s: %s" % (path, done.stderr))
    defined, weak, undefined = set(), set(), set()
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            raise SystemExit("tp_facts: unreadable nm line %r in %s" % (line, path))
        if parts[1] in UNDEFINED_TYPES:
            undefined.add(parts[0])
        else:
            defined.add(parts[0])
            if parts[1] in WEAK_DEFINED_TYPES:
                weak.add(parts[0])
    return sorted(defined), sorted(weak), sorted(undefined)


def unit(nm, name, obj):
    defined, weak, undefined = symbols(nm, obj)
    return {"name": name, "defined": defined, "weak": weak, "undefined": undefined, "pragmas": [],
            "attributes": [], "identifiers": [], "line_directives": []}


def main(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--label", required=True)
    parser.add_argument("--nm", required=True)
    parser.add_argument("--unit", nargs=2, action="append", default=[], metavar=("NAME", "OBJECT"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    units = sorted((unit(args.nm, *u) for u in args.unit), key=lambda u: u["name"])
    document = {"schema": 1, "label": args.label, "kind": "c_third_party", "deps": [], "units": units}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with open(args.out, "wb") as handle:
        handle.write(text.encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
