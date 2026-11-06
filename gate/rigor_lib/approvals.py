"""Signed sign-offs (approvals). Verified with `ssh-keygen -Y verify`; see docs/gate.md."""

import re

from rigor_lib import gitrun, paths
from rigor_lib.findings import finding

# `<sha256 of the json bytes>.json` and its signature `<same>.json.sig`.
APPROVAL_FILE_NAME = re.compile(rb"[0-9a-f]{64}\.json(\.sig)?")


def approval_lookalike_findings(repo, head_sha):
    """Approvals never live in the graded repo: any file named like one is a finding."""
    found = []
    for raw in gitrun.tree_paths(repo, head_sha):
        basename = raw.rsplit(b"/", 1)[-1]
        if APPROVAL_FILE_NAME.fullmatch(basename):
            found.append(finding("approval-in-repo", path=paths.display_path(raw)))
    return found
