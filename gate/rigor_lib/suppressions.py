"""`rigor suppressions`: no added line may switch off a check, plus no build products."""

from rigor_lib import approval_args, approvals, diffparse, gitrun, paths, patterns
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "suppressions"


def violation_scope(path, line, pattern_id):
    """The text an approval must carry to cover one violation."""
    return "%s:%d-%s" % (path, line, pattern_id)


def patch_violations(path_text, patch):
    """(line number, pattern id) for every forbidden pattern on every added line."""
    found = []
    for number, raw_line in diffparse.added_lines(patch):
        line_text = raw_line.decode("latin-1")  # lossless: every byte becomes one character
        for pattern_id in patterns.matching_pattern_ids(path_text, line_text):
            found.append((number, pattern_id))
    return found


def entry_findings(repo, base, head, entry, approval_set, used, seen):
    """Findings for one changed path. Ids of approvals that cover a violation go in `used`;
    every diff violation (reported or approved) goes in `seen` as (path, line, pattern)."""
    if entry.status == "D":
        return []
    shown = paths.display_path(entry.path)
    text = paths.match_text(entry.path)
    found = []
    if patterns.is_binary_artifact_name(text):
        found.append(finding("binary-artifact", path=shown))
    patch = gitrun.patch_for_path(repo, base, head, entry.path)
    for number, pattern_id in patch_violations(text, patch):
        seen.add((shown, number, pattern_id))
        approval = approval_set.covering(approvals.KIND_SUPPRESSION,
                                         violation_scope(shown, number, pattern_id))
        if approval is None:
            found.append(finding("forbidden-pattern", path=shown, line=number,
                                 pattern=pattern_id))
        else:
            used.add(approval.stem)
    return found


def text_violations(path_text, data):
    """(line number, pattern id) for every forbidden pattern on every line of a whole file."""
    found = []
    for number, raw_line in enumerate(data.split(b"\n"), start=1):
        for pattern_id in patterns.matching_pattern_ids(path_text, raw_line.decode("latin-1")):
            found.append((number, pattern_id))
    return found


def tree_findings(repo, entries, seen, approval_set, used):
    """`forbidden-pattern-in-tree` findings for lines of the graded tree the diff scan did not see.

    `entries` have `.path` (bytes) and `.blob`; `seen` holds the (path, line, pattern) triples the
    diff scan already handled (reported or approved), so a hit is never reported twice.
    """
    found = []
    for entry in entries:
        shown = paths.display_path(entry.path)
        data = gitrun.run_git(repo, ["cat-file", "blob", entry.blob])
        for number, pattern_id in text_violations(paths.match_text(entry.path), data):
            if (shown, number, pattern_id) in seen:
                continue
            approval = approval_set.covering(approvals.KIND_SUPPRESSION,
                                             violation_scope(shown, number, pattern_id))
            if approval is None:
                found.append(finding("forbidden-pattern-in-tree", path=shown, line=number,
                                     pattern=pattern_id))
            else:
                used.add(approval.stem)
    return found


def run(args, tree_entries=()):
    base, head = gitrun.resolve_range(args.repo, args.base, args.head)
    approval_set = approval_args.load_from_args(args)
    used = set()
    seen = set()
    found = list(approval_set.problems)
    for entry in gitrun.changed_entries(args.repo, base, head):
        found.extend(entry_findings(args.repo, base, head, entry, approval_set, used, seen))
    found.extend(tree_findings(args.repo, tree_entries, seen, approval_set, used))
    found.extend(approvals.approval_lookalike_findings(args.repo, head))
    metadata = {"merge_base": base, "head": head, "approvals_used": sorted(used)}
    return GateResult(GATE_ID, found, metadata)


def add_parser(subparsers):
    parser = subparsers.add_parser("suppressions", allow_abbrev=False,
                                   help="no added line may suppress a check")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--out")
    approval_args.add_approval_arguments(parser, repo_and_head_optional=False)
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
