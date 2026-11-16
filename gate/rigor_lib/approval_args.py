"""Command line options shared by the gates that accept approvals."""

from rigor_lib import approvals, gitrun
from rigor_lib.errors import InternalError


def add_approval_arguments(parser, repo_and_head_optional):
    """Add --approvals and --ledger; optionally also --repo and --head.

    The approval's repo-sha must be an ancestor of the graded head, so a gate with approvals
    needs a repository and head even if the gate itself reads no git data.
    """
    parser.add_argument("--approvals", help="directory of approval files (outside the repo)")
    parser.add_argument("--ledger", help="ledger directory: honour its tighten-only switch (off if absent)")
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
    return approvals.load_approvals(args.approvals, args.repo, head, getattr(args, "ledger", None))
