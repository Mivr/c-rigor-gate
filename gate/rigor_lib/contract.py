"""`rigor contract`: every changed path must be allowed and not protected."""

import tomllib

from rigor_lib import approvals, globs, gitrun, jsonio, paths
from rigor_lib.errors import InternalError
from rigor_lib.findings import GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "contract"
_KNOWN_KEYS = {"id", "allowed", "protected", "max_files"}
_PLAIN_MODES = {"100644", "100755", "000000"}  # 000000 = side where the path does not exist
_SYMLINK_MODE = "120000"
_SUBMODULE_MODE = "160000"


class Contract:
    def __init__(self, contract_id, allowed, protected, max_files):
        self.contract_id = contract_id
        self.allowed = allowed      # list of (pattern text, compiled glob)
        self.protected = protected  # list of (pattern text, compiled glob)
        self.max_files = max_files  # int or None


def _string_list(table, key, required):
    if key not in table:
        if required:
            raise InternalError("contract is missing key %r" % key)
        return []
    value = table[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InternalError("contract key %r must be a list of strings" % key)
    return value


def _compile_all(patterns):
    return [(pattern, globs.compile_glob(pattern)) for pattern in patterns]


def _max_files(table):
    if "max_files" not in table:
        return None
    value = table["max_files"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InternalError("contract key 'max_files' must be a non-negative integer")
    return value


def load_contract(path):
    table = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    unknown = sorted(set(table) - _KNOWN_KEYS)
    if unknown:
        raise InternalError("unknown contract keys: %s" % ", ".join(unknown))
    contract_id = table.get("id")
    if not isinstance(contract_id, str) or contract_id == "":
        raise InternalError("contract key 'id' must be a non-empty string")
    return Contract(contract_id,
                    _compile_all(_string_list(table, "allowed", required=True)),
                    _compile_all(_string_list(table, "protected", required=False)),
                    _max_files(table))


def _mode_findings(entry, shown):
    modes = (entry.old_mode, entry.new_mode)
    if _SYMLINK_MODE in modes:
        return [finding("symlink", path=shown)]
    if _SUBMODULE_MODE in modes:
        return [finding("submodule", path=shown)]
    unusual = [mode for mode in modes if mode not in _PLAIN_MODES]
    if unusual:
        return [finding("unsupported-mode", path=shown, mode=unusual[0])]
    return []


def _glob_findings(contract, text, shown):
    found = []
    if not any(globs.matches(glob, text) for _, glob in contract.allowed):
        found.append(finding("outside-allowed", path=shown))
    for pattern, glob in contract.protected:
        if globs.matches(glob, text):
            found.append(finding("protected", path=shown, pattern=pattern))
    return found


def entry_findings(contract, entry):
    shown = paths.display_path(entry.path)
    text = paths.match_text(entry.path)
    reason = paths.unsafe_path_reason(text)
    if reason is not None:
        return [finding("bad-path", path=shown, reason=reason)]
    return _mode_findings(entry, shown) + _glob_findings(contract, text, shown)


def check_entries(contract, entries):
    found = []
    for entry in entries:
        found.extend(entry_findings(contract, entry))
    if contract.max_files is not None and len(entries) > contract.max_files:
        found.append(finding("too-many-files", count=len(entries), max=contract.max_files))
    return found


def run(args):
    contract = load_contract(args.contract)
    base, head = gitrun.resolve_range(args.repo, args.base, args.head)
    entries = gitrun.changed_entries(args.repo, base, head)
    found = check_entries(contract, entries)
    found.extend(approvals.approval_lookalike_findings(args.repo, head))
    metadata = {"contract_id": contract.contract_id, "merge_base": base, "head": head,
                "changed_paths": len(entries)}
    return GateResult(GATE_ID, found, metadata)


def add_parser(subparsers):
    parser = subparsers.add_parser("contract", allow_abbrev=False,
                                   help="changed paths must be inside the task contract")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--out")
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
