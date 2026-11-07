#!/usr/bin/env -S python3 -I
"""Validate and hash perf bundles (docs/perf.md). `rigor grade --perf` loads and binds the same bundle.

    gate/tools/perf.py check DIR --product products/<p>/product.toml
    gate/tools/perf.py digest DIR

`check` loads the bundle (format, files, symlinks) and checks it against the product: the name in
product.toml, and every target's module in the policy.toml beside it at level L3 or above. It prints `ok`
and `perf_sha256`. `digest` prints `perf_sha256` after the format checks only. Exit 0 = done, 2 = any defect.
"""

import argparse
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

from rigor_lib import grade_policy, perf_bundle, product_layout  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(prog="perf.py", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", allow_abbrev=False)
    check.add_argument("dir")
    check.add_argument("--product", required=True, metavar="products/<p>/product.toml")
    digest = sub.add_parser("digest", allow_abbrev=False)
    digest.add_argument("dir")
    return parser


def run(args):
    bundle = perf_bundle.load(args.dir)
    if args.command == "digest":
        return perf_bundle.digest(bundle)
    name = product_layout.load_product(args.product).name
    levels = grade_policy.load_levels(os.path.join(os.path.dirname(args.product), "policy.toml"))
    perf_bundle.check(bundle, name, levels)
    return "ok %s" % perf_bundle.digest(bundle)


def main(argv):
    args = build_parser().parse_args(argv)
    try:
        print(run(args))
    except Exception as exc:  # any failure is exit 2, never a pass
        print("perf.py: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
