#!/usr/bin/env -S python3 -I
"""The decoupling baseline of a product (docs/decoupling.md): print it, or check the committed one.

    gate/tools/decoupling.py baseline --product-repo R --commit C --product NAME [--facts DIR] [--check]
                                      [--products-dir products]

Prints `products/<NAME>/decoupling-baseline.toml` for the tree of commit C of the product repository R: every
violation of the decoupling rules in that tree, sorted, the same bytes on every run. Nothing is written; redirect
the output. `--check` prints nothing and compares with the committed file instead (exit 1 and the difference on
stderr when they differ).

`--facts DIR` is the facts directory of a grade of that same commit (`<work>/facts`): with it the answer is exactly
what gate `decoupling` computes. Without it nothing is built: which dependency's symbols a target references is
then read from the text (a name of the dependency's policy `exports` in the target's own files), and the rules
that need the objects (`contract-has-behaviour`: `symbol`, `static-data`) see nothing. Use it for a first look;
the file that is pinned comes from `--facts`. Any unreadable input is exit 2. A summary per rule goes to stderr.
"""

import argparse
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

from rigor_lib import decoupling_baseline, decoupling_config, decoupling_rules, facts_data, facts_policy  # noqa: E402
from rigor_lib import gitrun, grade_decoupling, layering, product_layout  # noqa: E402
from rigor_lib.errors import InternalError  # noqa: E402

ARCHITECTURE_FILE = "architecture.toml"


def load_config(directory):
    path = os.path.join(directory, decoupling_config.FILE_NAME)
    if not os.path.isfile(path):
        raise InternalError("%s: the product has no %s" % (directory, decoupling_config.FILE_NAME))
    arch = os.path.join(directory, ARCHITECTURE_FILE)
    return decoupling_config.load(path, layering.load(arch) if os.path.isfile(arch) else None)


def policy_exports(directory):
    policy = facts_policy.load_policy(os.path.join(directory, "policy.toml"))
    return {label: module.exports for label, module in policy.modules.items() if module.exports is not None}


def uses(model, directory, facts_dir):
    if facts_dir is not None:
        return decoupling_rules.uses_from_facts(model, facts_data.load_facts_dir(facts_dir))
    return decoupling_rules.uses_from_text(model, policy_exports(directory))


def violations(repo, commit, directory, facts_dir):
    """{rule: {key: fields}} of the tree of `commit`, by the product files in `directory`."""
    if not os.path.isdir(repo):
        raise InternalError("product repo is not a local directory: %s" % repo)
    product = product_layout.load_product(os.path.join(directory, "product.toml"))
    model = grade_decoupling.commit_model(repo, gitrun.resolve_commit(repo, commit), product)
    return decoupling_rules.violations(model, load_config(directory), uses(model, directory, facts_dir))[0]


def difference(found, baseline):
    """Lines `+ rule: key` (a violation the file lacks) and `- rule: key` (an entry that is no violation)."""
    lines = []
    for rule in decoupling_rules.RULES:
        present = set(found[rule])
        lines += ["+ %s: %s" % (rule, key) for key in sorted(present - baseline[rule])]
        lines += ["- %s: %s" % (rule, key) for key in sorted(baseline[rule] - present)]
    return lines


def run(args):
    directory = os.path.join(args.products_dir, args.product)
    found = violations(args.product_repo, args.commit, directory, args.facts)
    for rule in decoupling_rules.RULES:
        print("%-28s %d" % (rule, len(found[rule])), file=sys.stderr)
    if not args.check:
        sys.stdout.write(decoupling_baseline.render(found))
        return 0
    lines = difference(found, grade_decoupling.load_baseline_file(directory))
    for line in lines:
        print(line, file=sys.stderr)
    return 1 if lines else 0


def main(argv):
    parser = argparse.ArgumentParser(prog="decoupling.py", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    baseline = sub.add_parser("baseline", allow_abbrev=False)
    baseline.add_argument("--product-repo", required=True)
    baseline.add_argument("--commit", required=True)
    baseline.add_argument("--product", required=True)
    baseline.add_argument("--facts", metavar="DIR")
    baseline.add_argument("--check", action="store_true")
    baseline.add_argument("--products-dir", default=os.path.join(os.path.dirname(
        os.path.realpath(__file__)), "..", "..", "products"))
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (InternalError, OSError) as exc:
        print("decoupling.py: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
