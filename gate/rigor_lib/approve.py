"""`rigor approve`: write an approval file (a recorded loosening; nobody signs it, see docs/trust.md)."""

from rigor_lib import approvals


def run(args):
    path = approvals.create_approval(args.kind, args.scope, args.reason, args.repo_sha,
                                     args.out_dir)
    print(path)
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser("approve", allow_abbrev=False,
                                   help="write an approval file (counted in every verdict that has it in force)")
    parser.add_argument("--kind", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--repo-sha", required=True)
    parser.add_argument("--out", dest="out_dir", required=True)
    parser.set_defaults(handler=run, gate_id=None)
