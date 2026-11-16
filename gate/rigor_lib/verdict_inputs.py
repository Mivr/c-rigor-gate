"""What decides a `rigor grade` verdict, bound into its hashed `core` (T021, R001 R4); `rigor verify` checks it (verdict_verify).

`core["inputs"]` holds the sha256 of every file the grade used and the ids of the commits it
graded. Files are *snapshotted* into `<work>/inputs/` first: the grade then reads only the
snapshot, and the hash is of the snapshot bytes, so nothing is hashed from one read and used
from another. The facts that come from the grade itself (commits from `clone`, the generated
`.buckconfig` and the pinned toolchain files from the `assemble` manifest) are read from the
gate results, never recomputed afterwards. See docs/grade.md ("Verdict inputs").
"""

import os
import re
import stat

from rigor_lib import grade_context, grade_tier, jsonio, oracle_bundle, perf_bundle, sim_policy, witness_bundle
from rigor_lib.errors import InternalError

_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
NO_PERF = "none"

INPUTS_DIR = "inputs"
TASK_NAME = "TASK.toml"
APPROVALS_NAME = "approvals"
WITNESS_NAME = "witness"
PERF_NAME = "perf"
ORACLE_NAME = "oracle"
# Files beside product.toml that the grade reads; the name is kept so path arithmetic still works.
PRODUCT_FILES = ("product.toml", "policy.toml", "expected-tests.json", "expected-tests.previous.json",
                 "ram-budget.toml", "architecture.toml", "fuzz-regressions.json", "decoupling.toml",
                 "decoupling-baseline.toml", "sim.toml", "sim-regressions.json", "sim-salt.public",
                 "oracle-policy.toml", "oracle-normalise.toml", "oracle-excluded.toml")
SIM_SALT_NAME = "sim-salt"   # the snapshot of the salt the sim gate builds with (grade_sim.SALT_NAME)
# U30 fix-up: every product configuration file the grade reads is bound by its own key (`sim-salt.public` is bound as
# `sim_salt_id`, the hash of the salt actually used). `rigor verify` recomputes these from the product directory.
PRODUCT_FILE_KEYS = {"product.toml": "product_toml_sha256", "policy.toml": "policy_sha256",
                     "expected-tests.json": "expected_tests_sha256",
                     "expected-tests.previous.json": "expected_tests_previous_sha256",
                     "ram-budget.toml": "ram_budget_sha256", "architecture.toml": "architecture_sha256",
                     "fuzz-regressions.json": "fuzz_regressions_sha256", "decoupling.toml": "decoupling_sha256",
                     "decoupling-baseline.toml": "decoupling_baseline_sha256", "sim.toml": "sim_spec_sha256",
                     "sim-regressions.json": "sim_regressions_sha256", "oracle-policy.toml": "oracle_policy_sha256",
                     "oracle-normalise.toml": "oracle_normalise_sha256",
                     "oracle-excluded.toml": "oracle_excluded_sha256"}

SHA_KEYS = ("task_sha256", "product_toml_sha256", "policy_sha256", "expected_tests_sha256",
            "expected_tests_previous_sha256", "ram_budget_sha256", "approvals_sha256",
            "order_sha256", "buckconfig_sha256", "toolchain_buck_sha256", "llvm_sha256",
            "sysroot_sha256", "buck2_sha256", "witness_sha256", "perf_sha256",
            "fuzz_regressions_sha256", "sim_spec_sha256", "sim_regressions_sha256", "sim_salt_id", "sim_seed_digest", "oracle_sha256", "oracle_policy_sha256", "oracle_normalise_sha256",
            "oracle_excluded_sha256", "architecture_sha256", "decoupling_sha256", "decoupling_baseline_sha256")
COMMIT_KEYS = ("gate_sha", "head", "base", "merge_base")
# `product_dir`: the product directory relative to the gate checkout (posix), or null when it lies outside it.
INPUT_KEYS = frozenset(SHA_KEYS + COMMIT_KEYS + ("gate_clean", "product", "uncached", "tier", "product_dir"))
# Absent on purpose in many grades: no approvals bundle, no previous expected-tests file, no witness, no perf bundle,
# no fuzz regression list, and nothing of the simulation (no sim.toml, no regressions, no salt, no `c_sim` run) and nothing of the oracle (no bundle, no policy, no table, no exclusions).
OPTIONAL_KEYS = frozenset({"approvals_sha256", "expected_tests_previous_sha256", "ram_budget_sha256", "witness_sha256",
                           "perf_sha256", "fuzz_regressions_sha256", "sim_spec_sha256", "sim_regressions_sha256",
                           "sim_salt_id", "sim_seed_digest", "oracle_sha256", "oracle_policy_sha256", "oracle_normalise_sha256",
                           "oracle_excluded_sha256", "architecture_sha256", "decoupling_sha256",
                           "decoupling_baseline_sha256"})
_REL_PATH = re.compile(r"(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[^\x00]+")


# ---------------------------------------------------------------- snapshot (read once, use the copy)

def snapshot_file(source, destination):
    """Copy `source` to `destination`; return the sha256 of the bytes copied, or None if unreadable.

    On None nothing is written, so a later read of `destination` fails the same way for the gate
    that needs it (a missing contract is that gate's internal error, not a crash here).
    """
    try:
        if os.path.islink(source) or not os.path.isfile(source):
            return None
        data = jsonio.read_bytes(source)
    except OSError:
        return None
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "xb") as handle:
        handle.write(data)
    return jsonio.sha256_hex(data)


def _approval_entry(source, destination):
    """[kind, sha256 or link target] for one top-level entry of the approvals bundle; copies it."""
    if os.path.islink(source):
        target = os.readlink(source)
        os.symlink(target, destination)
        return ["symlink", jsonio.sha256_hex(os.fsencode(target))]
    if os.path.isfile(source):
        data = jsonio.read_bytes(source)
        with open(destination, "xb") as handle:
            handle.write(data)
        return ["file", jsonio.sha256_hex(data)]
    os.mkdir(destination)  # a directory or special file: only its name is ever looked at
    return ["other", jsonio.sha256_hex(b"")]


def approvals_digest(source):
    """The digest `snapshot_approvals` binds, computed from a directory in place (for `rigor verify --approvals`)."""
    raw_source = os.fsencode(source)
    entries = []
    for name in sorted(os.listdir(raw_source)):
        path = os.path.join(raw_source, name)
        if os.path.islink(path):
            entry = ["symlink", jsonio.sha256_hex(os.fsencode(os.readlink(path)))]
        elif os.path.isfile(path):
            entry = ["file", jsonio.sha256_hex(jsonio.read_bytes(path))]
        else:
            entry = ["other", jsonio.sha256_hex(b"")]
        entries.append([os.fsdecode(name)] + entry)
    return jsonio.sha256_hex(jsonio.canonical_dumps(entries))


def snapshot_approvals(source, destination):
    """Copy the approvals directory and return the digest of its (name, kind, content hash) list."""
    if source is None:
        return None
    if not os.path.isdir(source):
        return None  # `destination` stays absent, so the approvals loader reports the bad path
    os.makedirs(destination)
    raw_source = os.fsencode(source)
    entries = []
    for name in sorted(os.listdir(raw_source)):
        kind = _approval_entry(os.path.join(raw_source, name),
                               os.path.join(os.fsencode(destination), name))
        entries.append([os.fsdecode(name)] + kind)
    return jsonio.sha256_hex(jsonio.canonical_dumps(entries))


def snapshot_sim_salt(hidden, public_copy, destination):
    """sim_salt_id (sha256 of the salt) of the salt this grade builds the simulations with, or None without one.

    The salt is the grader's `--sim-salt FILE` when given (hidden: only its sha256 ever enters a verdict), else the
    product's public `sim-salt.public` (already copied beside the other product files), else none. The text, normalised,
    is written to `destination`, which the `sim` gate reads. A bad salt is an InternalError (exit 2, before `clone`)."""
    if hidden is not None:
        if os.path.islink(hidden) or not os.path.isfile(hidden):
            raise InternalError("--sim-salt %s is not a regular file" % hidden)
        source = hidden
    elif os.path.isfile(public_copy):
        source = public_copy
    else:
        return None
    try:
        text = jsonio.read_bytes(source).decode("ascii")
    except UnicodeDecodeError as exc:
        raise InternalError("%s is not ASCII: %s" % (source, exc)) from exc
    salt = sim_policy.parse_salt(text, source)
    with open(destination, "xb") as handle:
        handle.write(salt.hex().encode("ascii") + b"\n")
    return jsonio.sha256_hex(salt)


def snapshot_inputs(args, work):
    """Copy every file input into `<work>/inputs`, point `args` at the copies, return the hashes."""
    base = os.path.join(work, INPUTS_DIR)
    os.makedirs(base)
    hashes = {}
    task_copy = os.path.join(base, TASK_NAME)
    hashes["task_sha256"] = snapshot_file(args.task, task_copy)
    args.task = task_copy
    product_dir = os.path.dirname(args.product)
    hashes["product_dir"] = gate_relative(product_dir)
    for name in PRODUCT_FILES:
        digest = snapshot_file(os.path.join(product_dir, name), os.path.join(base, "product", name))
        if name in PRODUCT_FILE_KEYS:
            hashes[PRODUCT_FILE_KEYS[name]] = digest
    args.product = os.path.join(base, "product", "product.toml")
    hashes["sim_salt_id"] = snapshot_sim_salt(getattr(args, "sim_salt", None),
                                              os.path.join(base, "product", "sim-salt.public"),
                                              os.path.join(base, SIM_SALT_NAME))
    if getattr(args, "sim_salt", None) is not None:
        args.sim_salt = os.path.join(base, SIM_SALT_NAME)
    approvals_copy = os.path.join(base, APPROVALS_NAME)
    hashes["approvals_sha256"] = snapshot_approvals(args.approvals, approvals_copy)
    if args.approvals is not None:
        args.approvals = approvals_copy
    _snapshot_trust_files(args, base, hashes)
    return hashes


def gate_relative(directory):
    """`directory` relative to the gate checkout (posix), or None when it is outside it (or is the root)."""
    root = os.path.realpath(grade_context.GATE_ROOT)
    path = os.path.realpath(directory)
    if os.path.commonpath([root, path]) != root or path == root:
        return None
    return os.path.relpath(path, root).replace(os.sep, "/")


def _snapshot_trust_files(args, base, hashes):
    """T071: copy the gate order into `<base>`, hash the copy, and point `args.order_file` at it; every
    reader in a grade uses only that copy."""
    copy = os.path.join(base, "order.txt")
    digest = snapshot_file(grade_context.ORDER_FILE, copy)
    if digest is None:
        raise InternalError("cannot snapshot order.txt (%s)" % grade_context.ORDER_FILE)
    hashes["order_sha256"] = digest
    args.order_file = copy


def _copy_regular(source, destination, what="witness bundle"):
    """Copy one regular file without following a symlink at its last component."""
    # O_NONBLOCK: a file swapped for a FIFO after the lstat cannot hang the grade.
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise InternalError("%s: not a regular file: %s" % (what, source))
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    with open(destination, "xb") as handle:
        handle.write(b"".join(chunks))


def _copy_bundle_tree(source, destination, what="witness bundle"):
    """Copy the directory `source` to `destination` (which must not exist); symlinks and special files
    are refused. Iterative. Empty directories and extra entries are copied, so `load` refuses them."""
    if not stat.S_ISDIR(os.lstat(source).st_mode):
        raise InternalError("%s is not a directory (or is a symlink): %s" % (what, source))
    os.mkdir(destination)
    pending = [""]
    while pending:
        rel = pending.pop()
        for name in sorted(os.listdir(os.path.join(source, rel))):
            child = os.path.join(rel, name)
            mode = os.lstat(os.path.join(source, child)).st_mode
            if stat.S_ISLNK(mode):
                raise InternalError("%s: symlink %s" % (what, child))
            if stat.S_ISDIR(mode):
                os.mkdir(os.path.join(destination, child))
                pending.append(child)
            elif stat.S_ISREG(mode):
                _copy_regular(os.path.join(source, child), os.path.join(destination, child), what)
            else:
                raise InternalError("%s: special file %s" % (what, child))


def snapshot_witness(source, destination):
    """(Bundle, witness_sha256) of the `--witness` bundle, or (None, None) without one (P002 Q1).

    The bundle is copied once to `destination`; the copy is loaded once, and that one load is both what
    the grade uses and what is hashed. Every defect (unreadable, symlink, special file, bad format) is
    an InternalError, so `rigor grade` stops with exit 2 before `clone`.
    """
    if source is None:
        return None, None
    try:
        _copy_bundle_tree(source, destination)
    except OSError as exc:
        raise InternalError("witness bundle: cannot copy %s: %s" % (source, exc)) from exc
    bundle = witness_bundle.load(destination)
    return bundle, witness_bundle.digest(bundle)


def snapshot_perf(source, destination, product_name, levels):
    """(Bundle, perf_sha256) of the `--perf` bundle, or (None, None) without one (R011, B13).

    Bound exactly like the witness bundle: copied once, the copy loaded once and checked against the
    product (name, policy modules at L3 or above), and that one load is both what the grade uses and what
    is hashed. Every defect is an InternalError, so `rigor grade` stops with exit 2 before `clone`.
    """
    if source is None:
        return None, None
    try:
        _copy_bundle_tree(source, destination, "perf bundle")
    except OSError as exc:
        raise InternalError("perf bundle: cannot copy %s: %s" % (source, exc)) from exc
    bundle = perf_bundle.load(destination)
    perf_bundle.check(bundle, product_name, levels)
    return bundle, perf_bundle.digest(bundle)


def snapshot_oracle(source, destination, product_name):
    """The oracle_sha256 of the `--oracle` bundle, or None without one (T2G7, P330 §3.3).

    Bound like the witness bundle: copied once, the copy loaded once and checked against the product name, and that one load
    is what is hashed; the `oracle` gate loads the same copy again (and refuses it if the hash differs). The bundle is the
    hidden half of the replay, so only this hash ever enters a verdict. Every defect is an InternalError (exit 2, before `clone`).
    """
    if source is None:
        return None
    try:
        _copy_bundle_tree(source, destination, "oracle bundle")
    except OSError as exc:
        raise InternalError("oracle bundle: cannot copy %s: %s" % (source, exc)) from exc
    bundle = oracle_bundle.load(destination)
    oracle_bundle.check(bundle, product_name)
    return oracle_bundle.digest(bundle)


# ---------------------------------------------------------------- facts from the grade itself

def pin_after(text, name):
    """sha256 of the `fetched_tree(name = "<name>", ...)` call in toolchains/BUCK."""
    match = re.search(r'name\s*=\s*"%s"\s*,[^)]*?sha256\s*=\s*"([0-9a-f]{64})"' % re.escape(name), text)
    if match is None:
        raise InternalError("toolchains/BUCK has no sha256 pin for %s" % name)
    return match.group(1)


def _tree_file(g, manifest, rel_path):
    """Bytes of a gate file of the grading tree, checked against what `assemble` recorded."""
    expected = manifest.get("gate/" + rel_path)
    if expected is None:
        raise InternalError("the assemble manifest has no gate/%s" % rel_path)
    data = jsonio.read_bytes(os.path.join(g.tree, "gate", rel_path))
    if jsonio.sha256_hex(data) != expected:
        raise InternalError("gate/%s changed after it was assembled" % rel_path)
    return data


def toolchain_pins(g, manifest):
    """(toolchains/BUCK sha, LLVM sha, sysroot sha, Buck2 binary sha) of the assembled tree."""
    buck = _tree_file(g, manifest, "toolchains/BUCK")
    text = buck.decode("utf-8")
    version = _tree_file(g, manifest, "tools/buck2.version").decode("ascii").strip()
    if not _SHA256.fullmatch(version):
        raise InternalError("tools/buck2.version is not a sha256")
    return (jsonio.sha256_hex(buck), pin_after(text, "llvm"), pin_after(text, "sysroot"), version)


def _metadata(documents, gate_id):
    document = documents.get(gate_id)
    return document["metadata"] if document is not None else {}


def _commit(metadata, key):
    value = metadata.get(key)
    return value if isinstance(value, str) and _FULL_SHA.fullmatch(value) else None


def build_inputs(g, documents):
    """The `inputs` object. Anything the grade did not get far enough to know is null."""
    clone = _metadata(documents, "clone")
    manifest = dict(_metadata(documents, "assemble").get("manifest", []))
    pins = (None, None, None, None)
    if manifest:
        pins = toolchain_pins(g, manifest)
    inputs = dict(g.inputs)
    inputs.update({
        "gate_sha": g.gate_sha, "gate_clean": bool(g.gate_clean),
        "head": _commit(clone, "head"), "base": _commit(clone, "base"),
        "merge_base": _commit(clone, "merge_base"),
        "product": g.product.name, "uncached": bool(g.args.uncached),
        "tier": grade_tier.tier_of(g),
        "sim_seed_digest": _metadata(documents, "sim").get("seed_digest"),
        "buckconfig_sha256": manifest.get(".buckconfig"),
        "toolchain_buck_sha256": pins[0], "llvm_sha256": pins[1],
        "sysroot_sha256": pins[2], "buck2_sha256": pins[3],
    })
    if set(inputs) != INPUT_KEYS:
        raise InternalError("verdict inputs are incomplete: %s" % sorted(INPUT_KEYS ^ set(inputs)))
    return inputs


def missing_inputs(inputs):
    """Names of required inputs that are null or malformed."""
    bad = []
    for key in sorted(INPUT_KEYS - OPTIONAL_KEYS - {"product_dir"}):
        value = inputs.get(key)
        if key in ("gate_clean", "uncached"):
            ok = isinstance(value, bool)
        elif key == "tier":
            ok = value in grade_tier.TIERS
        elif key == "product":
            ok = isinstance(value, str) and value != ""
        elif key in COMMIT_KEYS:
            ok = isinstance(value, str) and _FULL_SHA.fullmatch(value) is not None
        else:
            ok = isinstance(value, str) and _SHA256.fullmatch(value) is not None
        if not ok:
            bad.append(key)
    for key in sorted(OPTIONAL_KEYS):
        value = inputs.get(key)
        if value is not None and not (isinstance(value, str) and _SHA256.fullmatch(value)):
            bad.append(key)
    value = inputs.get("product_dir")
    if value is not None and not (isinstance(value, str) and _REL_PATH.fullmatch(value)):
        bad.append("product_dir")
    return sorted(bad)
