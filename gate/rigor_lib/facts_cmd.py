"""`rigor facts`: decide the two fact-based gates from the files `<name>_facts` produced."""

import argparse

from rigor_lib import facts_data, facts_modes, facts_policy, facts_semantic, facts_symbols, facts_third_party
from rigor_lib.errors import InternalError
from rigor_lib.runner import gate_handler

GATES = {facts_semantic.GATE_ID: "semantic", facts_symbols.GATE_ID: "symbols"}


class _GateChoice(argparse.Action):
    """Also sets `gate_id`, so an internal error replaces the right result file."""

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.gate = values
        namespace.gate_id = values


def run(args):
    if args.modes:
        args.gate_id = facts_modes.GATE_ID    # an internal error replaces the right result file
        if args.gate or args.facts or args.policy:
            raise InternalError("--modes takes no --gate, --facts or --policy")
        return facts_modes.run(args)
    if not (args.gate and args.facts and args.policy):
        raise InternalError("rigor facts needs --gate, --facts and --policy (or --modes)")
    facts = facts_data.load_facts_dir(args.facts)
    policy = facts_policy.load_policy(args.policy)
    third = facts_third_party.load(args.third_party)
    facts_third_party.check_policy(policy, third)
    if args.gate == facts_semantic.GATE_ID:
        return facts_semantic.run(facts, policy, third)
    if args.libc is None:
        raise InternalError("the symbols gate needs --libc")
    return facts_symbols.run(facts, policy, facts_data.load_symbol_list(args.libc), third)


def add_parser(subparsers):
    parser = subparsers.add_parser("facts", allow_abbrev=False,
                                   help="semantic suppressions and symbol policy from build facts")
    parser.add_argument("--gate", choices=sorted(GATES), action=_GateChoice)
    parser.add_argument("--facts")
    parser.add_argument("--policy")
    parser.add_argument("--modes", nargs=2, metavar=("RELEASE_DIR", "SAN_DIR"),
                        help="compare the release and san facts (gate mode-divergence)")
    parser.add_argument("--libc")
    parser.add_argument("--third-party", help="directory with ALLOWED_LABELS and RESERVED_PREFIXES "
                                              "(default: the gate's own third_party/)")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run))
