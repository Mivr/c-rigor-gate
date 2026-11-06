"""Signed sign-offs (approvals). Verified with `ssh-keygen -Y verify`; see docs/gate.md.

An approval is a canonical JSON file `<sha256>.json` (named by the hash of its bytes) with an
SSH signature `<sha256>.json.sig` made in the namespace `c-rigor-gate`. The signing key must
be listed in the gate's `allowed_signers`. Approvals live outside the graded repository.
"""

import os
import re
import subprocess
from dataclasses import dataclass

from rigor_lib import gitrun, jsonio, paths
from rigor_lib.errors import InternalError
from rigor_lib.findings import finding

NAMESPACE = "c-rigor-gate"
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
_SSH_TIMEOUT_SECONDS = 60

# `<sha256 of the json bytes>.json` and its signature `<same>.json.sig`.
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


def _ssh_keygen(args, input_bytes=None):
    """Run ssh-keygen; return (returncode, stdout bytes). A missing tool is an internal error."""
    env = {"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"}
    try:
        done = subprocess.run(["ssh-keygen"] + [os.fsencode(a) for a in args], env=env,
                              input=input_bytes if input_bytes is not None else b"",
                              capture_output=True, timeout=_SSH_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError("cannot run ssh-keygen: %s" % exc) from exc
    return done.returncode, done.stdout


def _principals_for(signature_path, allowed_signers):
    code, out = _ssh_keygen(["-Y", "find-principals", "-f", allowed_signers, "-s", signature_path])
    if code != 0:
        return []
    return [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]


def signature_is_valid(data, signature_path, allowed_signers, namespace=NAMESPACE):
    """True if some allowed principal's key signed exactly `data` in `namespace`."""
    for principal in _principals_for(signature_path, allowed_signers):
        code, _ = _ssh_keygen(["-Y", "verify", "-f", allowed_signers, "-I", principal,
                               "-n", namespace, "-s", signature_path], input_bytes=data)
        if code == 0:
            return True
    return False


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


def _check_one(directory, stem, allowed_signers):
    """Verify one `<stem>.json`. Returns (Approval or None, problem reason or None)."""
    json_path = os.path.join(directory, stem + b".json")
    signature_path = json_path + b".sig"
    if not os.path.isfile(json_path) or os.path.islink(json_path):
        return None, "unrecognised-file"
    if not os.path.isfile(signature_path):
        return None, "unsigned"
    data = jsonio.read_bytes(json_path)
    if jsonio.sha256_hex(data).encode("ascii") != stem:
        return None, "name-mismatch"
    if not signature_is_valid(data, signature_path, allowed_signers):
        return None, "signature-rejected"
    approval = _parse_document(data, stem.decode("ascii"))
    if approval is None:
        return None, "malformed"
    return approval, None


def _classify_names(names):
    """Split directory names into approval stems and everything else."""
    stems = set()
    orphans = []
    others = []
    for name in names:
        if not APPROVAL_FILE_NAME.fullmatch(name):
            others.append(name)
        elif name.endswith(b".json"):
            stems.add(name[:-len(b".json")])
    for name in names:
        if name.endswith(b".json.sig") and APPROVAL_FILE_NAME.fullmatch(name):
            if name[:-len(b".json.sig")] not in stems:
                orphans.append(name)
    return sorted(stems), sorted(orphans), sorted(others)


def load_approvals(directory, repo, head_sha, allowed_signers):
    """Verify every file in the approvals directory against the graded head."""
    raw_directory = os.fsencode(directory)
    if not os.path.isdir(raw_directory):
        raise InternalError("approvals path is not a directory: %s" % directory)
    names = sorted(os.listdir(raw_directory))
    if not names:
        return EMPTY
    if not os.path.isfile(allowed_signers):
        raise InternalError("allowed_signers file not found: %s" % allowed_signers)
    stems, orphans, others = _classify_names(names)
    problems = [_forged(name, "unrecognised-file") for name in others]
    problems += [_forged(name, "orphan-signature") for name in orphans]
    valid = []
    for stem in stems:
        approval, reason = _check_one(raw_directory, stem, allowed_signers)
        if reason is not None:
            problems.append(_forged(stem + b".json", reason))
        elif _applies_to(approval, repo, head_sha):
            valid.append(approval)
    return ApprovalSet(valid, problems)


def create_approval(kind, scope, reason, repo_sha, key_path, out_dir):
    """Write `<sha256>.json` and sign it. Returns the path of the JSON file."""
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
    try:
        _sign(json_path, key_path)
    except Exception:
        _remove_quietly(json_path)
        _remove_quietly(json_path + ".sig")
        raise
    return json_path


def _sign(json_path, key_path):
    code, _ = _ssh_keygen(["-Y", "sign", "-n", NAMESPACE, "-f", key_path, json_path])
    if code != 0 or not os.path.isfile(json_path + ".sig"):
        raise InternalError("ssh-keygen could not sign the approval")


def _remove_quietly(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
