"""`rigor facts`: decide the two fact-based gates from the files `<name>_facts` produced."""

import argparse

from rigor_lib import facts_data, facts_policy, facts_semantic, facts_symbols
from rigor_lib.errors import InternalError
from rigor_lib.runner import gate_handler

GATES = {facts_semantic.GATE_ID: "semantic", facts_symbols.GATE_ID: "symbols"}


class _GateChoice(argparse.Action):
    """Also sets `gate_id`, so an internal error replaces the right result file."""

    def __call__(self, parser, namespace, values, option_string=None):
        namespace.gate = values
        namespace.gate_id = values


def run(args):
    facts = facts_data.load_facts_dir(args.facts)
    policy = facts_policy.load_policy(args.policy)
    if args.gate == facts_semantic.GATE_ID:
        return facts_semantic.run(facts, policy)
    if args.libc is None:
        raise InternalError("the symbols gate needs --libc")
    return facts_symbols.run(facts, policy, facts_data.load_symbol_list(args.libc))


def add_parser(subparsers):
    parser = subparsers.add_parser("facts", allow_abbrev=False,
                                   help="semantic suppressions and symbol policy from build facts")
    parser.add_argument("--gate", required=True, choices=sorted(GATES), action=_GateChoice)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--libc")
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run))
