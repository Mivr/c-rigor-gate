"""Append-only hash-chained ledger of claims, revocations and gate events (P003 section 10; docs/trust.md).

A ledger is a directory of `NNNNNN.jsonl` files. Each line is one canonical-JSON entry:
`seq` (dense from 1), `prev` (sha256 of the previous entry's bytes, 64 zeros for the first), `kind`,
`subject`, `evidence` (sha256 of the evidence bytes, or "") and `at` (UTC seconds given by the caller;
this module never reads a clock). The head is the sha256 of the last entry's bytes.
"""

import os
import re

from rigor_lib import jsonio
from rigor_lib.errors import InternalError

KIND_CLAIM = "claim"
KIND_REVOCATION = "revocation"
KIND_RATCHET = "ratchet"
KIND_GATE_CHANGE = "gate-change"
KIND_TIGHTEN_ON = "tighten-only-on"
KIND_TIGHTEN_OFF = "tighten-only-off"
KINDS = (KIND_CLAIM, KIND_REVOCATION, KIND_RATCHET, KIND_GATE_CHANGE, KIND_TIGHTEN_ON,
         KIND_TIGHTEN_OFF)

ZERO_HASH = "0" * 64
ENTRIES_PER_FILE = 1000
EQUIVALENT_MUTANT = "equivalent-mutant"

# Debt cap: unproved equivalent-mutant claims per module, in parts per million of its mutants (2%).
DEFAULT_CAP_PPM = 20000
SMALL_MODULE_MUTANTS = 50  # a module with fewer mutants than this may hold one claim

_ENTRY_KEYS = {"seq", "prev", "kind", "subject", "evidence", "at"}
_FILE_NAME = re.compile(r"([0-9]{6})\.jsonl")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class LedgerError(InternalError):
    """The ledger does not verify, or an append was refused."""


def _is_int(value):
    return type(value) is int


def _parse_entry(line, expected_seq, expected_prev):
    """Strictly parse one line (with its newline); return the entry dict or raise LedgerError."""
    try:
        entry = jsonio.strict_loads(line)
    except ValueError as exc:
        raise LedgerError("entry %d is not valid JSON: %s" % (expected_seq, exc)) from exc
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise LedgerError("entry %d has the wrong keys" % expected_seq)
    if jsonio.canonical_dumps(entry) != line:
        raise LedgerError("entry %d is not canonical JSON" % expected_seq)
    if not _is_int(entry["seq"]) or entry["seq"] != expected_seq:
        raise LedgerError("entry %d: seq is %r (gap, duplicate or reorder)" % (expected_seq, entry["seq"]))
    if entry["prev"] != expected_prev:
        raise LedgerError("entry %d: prev does not match the previous entry" % expected_seq)
    _check_fields(entry)
    return entry


def _check_fields(entry):
    seq = entry["seq"]
    if entry["kind"] not in KINDS:
        raise LedgerError("entry %d: unknown kind %r" % (seq, entry["kind"]))
    if not isinstance(entry["subject"], str) or entry["subject"] == "":
        raise LedgerError("entry %d: subject must be a non-empty string" % seq)
    evidence = entry["evidence"]
    if not isinstance(evidence, str) or (evidence != "" and not _HEX64.fullmatch(evidence)):
        raise LedgerError("entry %d: evidence must be empty or a sha256" % seq)
    if not _is_int(entry["at"]) or entry["at"] < 0:
        raise LedgerError("entry %d: at must be a non-negative integer" % seq)


def _file_names(ledger):
    """Sorted names in the directory; any name that is not `NNNNNN.jsonl` is a stray file."""
    if not os.path.isdir(ledger):
        raise LedgerError("ledger path is not a directory: %s" % ledger)
    names = sorted(os.listdir(ledger))
    for index, name in enumerate(names, start=1):
        match = _FILE_NAME.fullmatch(name)
        if match is None or int(match.group(1)) != index:
            raise LedgerError("stray or missing ledger file: %s" % name)
        path = os.path.join(ledger, name)
        if os.path.islink(path) or not os.path.isfile(path):
            raise LedgerError("ledger file is not a regular file: %s" % name)
    return names


def _file_lines(path):
    data = jsonio.read_bytes(path)
    if data == b"":
        raise LedgerError("empty ledger file: %s" % os.path.basename(path))
    if not data.endswith(b"\n"):
        raise LedgerError("ledger file does not end in a newline: %s" % os.path.basename(path))
    return data.splitlines(keepends=True)


def read_entries(ledger):
    """All entries in order, after checking the chain. Returns (entries, hashes); raises LedgerError."""
    entries = []
    hashes = []
    prev = ZERO_HASH
    for name in _file_names(ledger):
        for line in _file_lines(os.path.join(ledger, name)):
            entry = _parse_entry(line, len(entries) + 1, prev)
            prev = jsonio.sha256_hex(line)
            entries.append(entry)
            hashes.append(prev)
    return entries, hashes


def head(ledger):
    """The sha256 of the last entry's bytes (64 zeros for an empty ledger). Verifies the chain."""
    _, hashes = read_entries(ledger)
    return hashes[-1] if hashes else ZERO_HASH


def verify(ledger, expected_head=None):
    """Return the head; raise LedgerError unless the chain is intact. With `expected_head` the chain must
    contain that head (a longer chain is growth, a shorter or different one is truncation or rewrite)."""
    _, hashes = read_entries(ledger)
    if expected_head is not None and expected_head != ZERO_HASH and expected_head not in hashes:
        raise LedgerError("head %s is not in the ledger (truncated or rewritten)" % expected_head)
    return hashes[-1] if hashes else ZERO_HASH


def make_subject(approval_kind, scope, approval_sha256):
    return "%s:%s:%s" % (approval_kind, scope, approval_sha256)


def split_subject(subject):
    """(approval kind, scope, sha256) of a claim subject, or None if it is not of that form."""
    head_part, _, sha = subject.rpartition(":")
    approval_kind, _, scope = head_part.partition(":")
    if not _HEX64.fullmatch(sha) or approval_kind == "" or scope == "":
        return None
    return approval_kind, scope, sha


def standing_claims(ledger):
    """Claim entries that were not revoked, sorted by subject. A later claim of a revoked subject stands."""
    entries, _ = read_entries(ledger)
    return _standing_from(entries)


def _standing_from(entries):
    standing = {}
    for entry in entries:
        if entry["kind"] == KIND_CLAIM:
            standing[entry["subject"]] = entry
        elif entry["kind"] == KIND_REVOCATION:
            standing.pop(entry["subject"], None)
    return [standing[subject] for subject in sorted(standing)]


def tighten_only_since(ledger):
    """The `seq` of the `tighten-only-on` entry that is in force, or None when the switch is off."""
    entries, _ = read_entries(ledger)
    since = None
    for entry in entries:
        if entry["kind"] == KIND_TIGHTEN_ON and since is None:
            since = entry["seq"]
        elif entry["kind"] == KIND_TIGHTEN_OFF:
            since = None
    return since


def tighten_only(ledger):
    return tighten_only_since(ledger) is not None


def claim_seqs(ledger):
    """{claim subject: seq of its latest claim entry}."""
    entries, _ = read_entries(ledger)
    return {e["subject"]: e["seq"] for e in entries if e["kind"] == KIND_CLAIM}


def debt(standing, module_mutants):
    """{module: number of standing `equivalent-mutant` claims on its mutants}.

    `module_mutants` maps module -> collection of its mutant ids; a claim's scope is a mutant id."""
    counts = {module: 0 for module in module_mutants}
    for entry in standing:
        parts = split_subject(entry["subject"])
        if entry["kind"] != KIND_CLAIM or parts is None or parts[0] != EQUIVALENT_MUTANT:
            continue
        for module, ids in module_mutants.items():
            if parts[1] in ids:
                counts[module] += 1
    return counts


def allowed_debt(mutants, cap_ppm=DEFAULT_CAP_PPM):
    """How many claims a module with `mutants` mutants may hold (integer arithmetic, rounded down)."""
    allowed = mutants * cap_ppm // 1000000
    if mutants < SMALL_MODULE_MUTANTS:
        return max(allowed, 1)
    return allowed


def over_cap(count, mutants, cap_ppm=DEFAULT_CAP_PPM):
    return count > allowed_debt(mutants, cap_ppm)


def _validate_new(entries, kind, subject, evidence):
    if kind not in KINDS:
        raise LedgerError("unknown ledger entry kind: %r" % kind)
    if not isinstance(subject, str) or subject == "":
        raise LedgerError("subject must be a non-empty string")
    if kind in (KIND_CLAIM, KIND_REVOCATION):
        if split_subject(subject) is None:
            raise LedgerError("subject must be <approval kind>:<scope>:<sha256>")
        stands = subject in [e["subject"] for e in _standing_from(entries)]
        if kind == KIND_CLAIM and stands:
            raise LedgerError("claim already stands: %s" % subject)
        if kind == KIND_REVOCATION and (not stands or evidence == ""):
            raise LedgerError("a revocation needs a standing claim and refuting evidence")


def _target_file(ledger, names, count):
    """Path of the file the next entry goes to; a new file when the last one is full."""
    if not names:
        return os.path.join(ledger, "000001.jsonl")
    if count % ENTRIES_PER_FILE == 0:
        return os.path.join(ledger, "%06d.jsonl" % (len(names) + 1))
    return os.path.join(ledger, names[-1])


def append(ledger, kind, subject, evidence_sha256, at):
    """Append one entry after verifying the chain. Returns the new head."""
    entries, hashes = read_entries(ledger)
    if not _is_int(at) or at < 0:
        raise LedgerError("at must be a non-negative integer")
    _validate_new(entries, kind, subject, evidence_sha256)
    entry = {"seq": len(entries) + 1, "prev": hashes[-1] if hashes else ZERO_HASH, "kind": kind,
             "subject": subject, "evidence": evidence_sha256, "at": at}
    _check_fields(entry)
    line = jsonio.canonical_dumps(entry)
    path = _target_file(ledger, _file_names(ledger), len(entries))
    old = jsonio.read_bytes(path) if os.path.isfile(path) else b""
    jsonio.write_atomic(path, old + line)
    return jsonio.sha256_hex(line)


# --- command line: `rigor ledger append|verify|claims` ---------------------------------------------------------


def _run_append(args):
    os.makedirs(args.ledger, exist_ok=True)
    evidence = ""
    if args.evidence is not None:
        evidence = jsonio.sha256_hex(jsonio.read_bytes(args.evidence))
    print(append(args.ledger, args.kind, args.subject, evidence, args.at))
    return 0


def _run_verify(args):
    try:
        print(verify(args.ledger, args.head))
    except LedgerError as exc:
        print("ledger: %s" % exc)
        return 1
    return 0


def _run_claims(args):
    for entry in standing_claims(args.ledger):
        print("%s\t%d\t%s" % (entry["subject"], entry["seq"], entry["evidence"]))
    return 0


def add_parser(subparsers):
    parser = subparsers.add_parser("ledger", allow_abbrev=False, help="append-only claim ledger")
    sub = parser.add_subparsers(dest="ledger_command", required=True)
    add = sub.add_parser("append", allow_abbrev=False, help="append one entry")
    add.add_argument("--ledger", required=True)
    add.add_argument("--kind", required=True)
    add.add_argument("--subject", required=True)
    add.add_argument("--evidence")
    add.add_argument("--at", type=int, required=True)
    add.set_defaults(handler=_run_append, gate_id=None)
    check = sub.add_parser("verify", allow_abbrev=False, help="verify the chain; print the head")
    check.add_argument("--ledger", required=True)
    check.add_argument("--head")
    check.set_defaults(handler=_run_verify, gate_id=None)
    claims = sub.add_parser("claims", allow_abbrev=False, help="list standing claims")
    claims.add_argument("--ledger", required=True)
    claims.set_defaults(handler=_run_claims, gate_id=None)
