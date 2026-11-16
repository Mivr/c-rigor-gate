"""Command line options shared by the gates that accept approvals."""

import os

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


def _inside(path, directory):
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return os.path.commonpath([path, directory]) == directory


def graded_side_directories(args):
    """(name, directory) of every input the graded side can write: the product repository, the work directory,
    the witness, oracle and perf bundles and the directory holding the task contract (those given)."""
    task = getattr(args, "task", None)
    named = (("the product repository", getattr(args, "product_repo", None)), ("the work directory", args.work),
             ("the --witness bundle", getattr(args, "witness", None)),
             ("the --oracle bundle", getattr(args, "oracle", None)), ("the --perf bundle", getattr(args, "perf", None)),
             ("the directory of --task", os.path.dirname(task) if task else None))
    return [(name, directory) for name, directory in named if directory]


def refuse_planted_approvals(args):
    """U30 fix-up: nobody signs an approval, so an approvals directory the graded party can write would be in
    force. One inside any of `graded_side_directories` is refused (exit 2)."""
    if args.approvals is None:
        return
    for name, directory in graded_side_directories(args):
        if _inside(args.approvals, directory):
            raise InternalError("--approvals %s is inside %s: approvals must live outside what is graded"
                                % (args.approvals, name))
