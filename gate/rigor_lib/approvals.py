"""Approvals: the recorded loosenings a gate honours (docs/gate.md, docs/trust.md).

An approval is a canonical JSON file `<sha256>.json` (named by the hash of its bytes) with a kind, the
exact scope it covers, a reason and the commit it was written against. Nobody signs it (U30): it counts
because it is schema-checked, covers exactly its scope and nothing else, applies only to heads that
descend from its commit, and is counted and listed in every verdict that has it in force. Approvals live
outside the graded repository; a `.json.sig` file left by the signing gate is refused, not ignored.
"""

import os
import re
from dataclasses import dataclass

from rigor_lib import gitrun, jsonio, ledger as ledger_lib, paths
from rigor_lib.errors import InternalError
from rigor_lib.findings import finding

KIND_SUPPRESSION = "suppression"
KIND_TEST_REMOVAL = "test-removal"
KIND_RATCHET = "ratchet"
KIND_EQUIVALENT_MUTANT = "equivalent-mutant"
KINDS = (KIND_SUPPRESSION, KIND_TEST_REMOVAL, KIND_RATCHET, KIND_EQUIVALENT_MUTANT)

# --- BEGIN witness-equivalent-mutant (P002 Q3, owner decision 4: NOT YET CONFIRMED) ---------------
# An equivalent mutant of the gate-held witness (gate `mutants-witness`), kept apart from
# `equivalent-mutant` so that an approval written for the witness can never cover a same-id mutant of
# the implementer's code. If the owner rejects the kind, delete this block; nothing else refers to it.
KIND_WITNESS_EQUIVALENT_MUTANT = "witness-equivalent-mutant"
KINDS = KINDS + (KIND_WITNESS_EQUIVALENT_MUTANT,)
# --- END witness-equivalent-mutant ------------------------------------------------------------------
_DOCUMENT_KEYS = {"kind", "scope", "reason", "repo_sha"}
_FULL_SHA = re.compile(r"[0-9a-f]{40}")

# `<sha256 of the json bytes>.json`, and the `<same>.json.sig` the signing gate wrote beside it (still
# recognised, so it can never pass unnoticed: in the graded repo it is `approval-in-repo`, in the
# approvals directory `signature-file`).
APPROVAL_FILE_NAME = re.compile(rb"[0-9a-f]{64}\.json(\.sig)?")


@dataclass(frozen=True)
class Approval:
    kind: str
    scope: str
    reason: str
    repo_sha: str
    stem: str  # sha256 of the approval's JSON bytes


class ApprovalSet:
    """Approvals that verified and apply to the graded head, plus problems found."""

    def __init__(self, valid, problems):
        self.valid = valid
        self.problems = problems  # list of forged-approval findings

    def covering(self, kind, scope):
        """The approval for exactly this kind and scope, or None."""
        for approval in self.valid:
            if approval.kind == kind and approval.scope == scope:
                return approval
        return None


EMPTY = ApprovalSet([], [])


def approval_lookalike_findings(repo, head_sha):
    """Approvals never live in the graded repo: any file named like one is a finding."""
    found = []
    for raw in gitrun.tree_paths(repo, head_sha):
        basename = raw.rsplit(b"/", 1)[-1]
        if APPROVAL_FILE_NAME.fullmatch(basename):
            found.append(finding("approval-in-repo", path=paths.display_path(raw)))
    return found


def _is_nonempty_string(value):
    return isinstance(value, str) and value != ""


def _parse_document(data, stem):
    """Strictly parse approval JSON; None if malformed."""
    try:
        document = jsonio.strict_loads(data)
    except ValueError:
        return None
    if not isinstance(document, dict) or set(document) != _DOCUMENT_KEYS:
        return None
    if document["kind"] not in KINDS:
        return None
    if not _is_nonempty_string(document["scope"]) or not _is_nonempty_string(document["reason"]):
        return None
    sha = document["repo_sha"]
    if not isinstance(sha, str) or not _FULL_SHA.fullmatch(sha):
        return None
    return Approval(document["kind"], document["scope"], document["reason"], sha, stem)


def _forged(file_name, reason):
    return finding("forged-approval", file=paths.display_path(file_name), reason=reason)


def _applies_to(approval, repo, head_sha):
    """An approval is usable only if its repo_sha is an ancestor of the graded head."""
    return (gitrun.commit_exists(repo, approval.repo_sha)
            and gitrun.is_ancestor(repo, approval.repo_sha, head_sha))


def _check_one(directory, stem):
    """Check one `<stem>.json`. Returns (Approval or None, problem reason or None)."""
    json_path = os.path.join(directory, stem + b".json")
    if not os.path.isfile(json_path) or os.path.islink(json_path):
        return None, "unrecognised-file"
    data = jsonio.read_bytes(json_path)
    if jsonio.sha256_hex(data).encode("ascii") != stem:
        return None, "name-mismatch"
    approval = _parse_document(data, stem.decode("ascii"))
    if approval is None:
        return None, "malformed"
    return approval, None


def _tighten_reason(approval, since, claims):
    """"tighten-only" if the switch is on and this approval's claim entry came after the switch was turned on."""
    subject = ledger_lib.make_subject(approval.kind, approval.scope, approval.stem)
    seq = claims.get(subject)
    if since is not None and seq is not None and seq > since:
        return "tighten-only"
    return None


def _classify_names(names):
    """Split directory names into approval stems, signature files and everything else."""
    stems = set()
    signatures = []
    others = []
    for name in names:
        if not APPROVAL_FILE_NAME.fullmatch(name):
            others.append(name)
        elif name.endswith(b".json"):
            stems.add(name[:-len(b".json")])
        else:
            signatures.append(name)
    return sorted(stems), sorted(signatures), sorted(others)


def load_approvals(directory, repo, head_sha, ledger=None):
    """Check every file in the approvals directory against the graded head.

    `ledger`: a ledger directory; when its tighten-only switch is on, an approval whose claim entry
    comes after the `tighten-only-on` entry does not count. Without it, nothing changes."""
    raw_directory = os.fsencode(directory)
    if not os.path.isdir(raw_directory):
        raise InternalError("approvals path is not a directory: %s" % directory)
    names = sorted(os.listdir(raw_directory))
    if not names:
        return EMPTY
    stems, signatures, others = _classify_names(names)
    problems = [_forged(name, "unrecognised-file") for name in others]
    problems += [_forged(name, "signature-file") for name in signatures]
    since = ledger_lib.tighten_only_since(ledger) if ledger is not None else None
    claims = ledger_lib.claim_seqs(ledger) if since is not None else {}
    valid = []
    for stem in stems:
        approval, reason = _check_one(raw_directory, stem)
        if reason is None:
            reason = _tighten_reason(approval, since, claims)
        if reason is not None:
            problems.append(_forged(stem + b".json", reason))
        elif _applies_to(approval, repo, head_sha):
            valid.append(approval)
    return ApprovalSet(valid, problems)


def create_approval(kind, scope, reason, repo_sha, out_dir):
    """Write `<sha256>.json`. Returns its path. Nothing is signed: the file is the record."""
    if kind not in KINDS:
        raise InternalError("unknown approval kind: %r" % kind)
    if not _is_nonempty_string(scope) or not _is_nonempty_string(reason):
        raise InternalError("scope and reason must be non-empty")
    if not _FULL_SHA.fullmatch(repo_sha):
        raise InternalError("repo-sha must be a full lowercase 40-hex commit id")
    data = jsonio.canonical_dumps({"kind": kind, "scope": scope, "reason": reason,
                                   "repo_sha": repo_sha})
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, jsonio.sha256_hex(data) + ".json")
    jsonio.write_atomic(json_path, data)
    return json_path
