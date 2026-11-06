#!/usr/bin/env -S python3 -I
"""Maintain `products/<P>/expected-tests.json`: add-only.

    gate/tools/expected.py add --product P --results DIR [DIR...] [--products-dir products]

Merges every test id found in the `*.jsonl` result files of the DIRs into the product's list
(sorted, no duplicates). It never removes an id: dropping an expected test needs a signed
`test-removal` approval and a manual edit. Malformed result files, an unreadable list, or a merge
that would lose an id are errors (exit 2) and leave the list untouched.
"""

import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

from rigor_lib import jsonio, tests_gate  # noqa: E402
from rigor_lib.errors import InternalError  # noqa: E402


def ids_in_results(directories):
    found = set()
    for directory in directories:
        for parsed in tests_gate.parse_results_directory(directory):
            if parsed.problems:
                raise InternalError("%s/%s: malformed results: %s" % (directory, parsed.name, parsed.problems[0]))
            found.update(record.test_id for record in parsed.records)
    return found


def merge(existing, found):
    merged = sorted(set(existing) | set(found))
    if not set(existing) <= set(merged):  # cannot happen; this is the add-only guarantee
        raise InternalError("refusing to remove expected test ids")
    return merged


def add(products_dir, product, directories):
    path = os.path.join(products_dir, product, "expected-tests.json")
    existing = tests_gate.load_id_list(path) if os.path.exists(path) else set()
    merged = merge(existing, ids_in_results(directories))
    data = json.dumps({"ids": merged}) + "\n"
    jsonio.write_atomic(path, data.encode("utf-8"))
    return len(merged) - len(existing), len(merged)


def main(argv):
    parser = argparse.ArgumentParser(prog="expected.py", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser = sub.add_parser("add", allow_abbrev=False)
    add_parser.add_argument("--product", required=True)
    add_parser.add_argument("--results", required=True, nargs="+")
    add_parser.add_argument("--products-dir", default=os.path.join(os.path.dirname(
        os.path.realpath(__file__)), "..", "..", "products"))
    args = parser.parse_args(argv)
    try:
        added, total = add(args.products_dir, args.product, args.results)
    except InternalError as exc:
        print("expected.py: %s" % exc, file=sys.stderr)
        return 2
    print("%s: added %d, now %d ids" % (args.product, added, total))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
