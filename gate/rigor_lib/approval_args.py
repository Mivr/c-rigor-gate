"""Command line options shared by the gates that accept approvals."""

import os

from rigor_lib import approvals, gitrun
from rigor_lib.errors import InternalError

DEFAULT_ALLOWED_SIGNERS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "allowed_signers")


def add_approval_arguments(parser, repo_and_head_optional):
    """Add --approvals and --allowed-signers; optionally also --repo and --head.

    The approval's repo-sha must be an ancestor of the graded head, so a gate with approvals
    needs a repository and head even if the gate itself reads no git data.
    """
    parser.add_argument("--approvals", help="directory of signed approvals (outside the repo)")
    parser.add_argument("--allowed-signers", default=DEFAULT_ALLOWED_SIGNERS,
                        help="allowed_signers file (default: the one shipped in gate/)")
    if repo_and_head_optional:
        parser.add_argument("--repo", help="graded repository (required with --approvals)")
        parser.add_argument("--head", help="graded head revision (required with --approvals)")


def load_from_args(args):
    """The ApprovalSet for these arguments; empty when --approvals was not given."""
    if args.approvals is None:
        return approvals.EMPTY
    if args.repo is None or args.head is None:
        raise InternalError("--approvals needs --repo and --head")
    head = gitrun.resolve_commit(args.repo, args.head)
    return approvals.load_approvals(args.approvals, args.repo, head, args.allowed_signers)
