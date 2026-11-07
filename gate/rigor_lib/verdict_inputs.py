"""What decides a `rigor grade` verdict, bound into the signed `core` (T021, R001 R4), and `rigor verify`.

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

from rigor_lib import approval_args, approvals, grade_context, grade_policy, jsonio, perf_bundle, witness_bundle
from rigor_lib.errors import InternalError
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS

VERDICT_NAMESPACE = "c-rigor-gate-verdict"
_PASS = "PASS"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
NO_PERF = "none"

INPUTS_DIR = "inputs"
TASK_NAME = "TASK.toml"
APPROVALS_NAME = "approvals"
WITNESS_NAME = "witness"
PERF_NAME = "perf"
# Files beside product.toml that the grade reads; the name is kept so path arithmetic still works.
PRODUCT_FILES = ("product.toml", "policy.toml", "expected-tests.json", "expected-tests.previous.json",
                 "architecture.toml")

SHA_KEYS = ("task_sha256", "product_toml_sha256", "policy_sha256", "expected_tests_sha256",
            "expected_tests_previous_sha256", "approvals_sha256", "allowed_signers_sha256",
            "order_sha256", "buckconfig_sha256", "toolchain_buck_sha256", "llvm_sha256",
            "sysroot_sha256", "buck2_sha256", "witness_sha256", "perf_sha256")
COMMIT_KEYS = ("gate_sha", "head", "base", "merge_base")
INPUT_KEYS = frozenset(SHA_KEYS + COMMIT_KEYS + ("gate_clean", "product", "uncached"))
# Absent on purpose in many grades: no approvals bundle, no previous expected-tests file, no witness, no perf bundle.
OPTIONAL_KEYS = frozenset({"approvals_sha256", "expected_tests_previous_sha256", "witness_sha256", "perf_sha256"})


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


def snapshot_inputs(args, work):
    """Copy every file input into `<work>/inputs`, point `args` at the copies, return the hashes."""
    base = os.path.join(work, INPUTS_DIR)
    os.makedirs(base)
    hashes = {}
    task_copy = os.path.join(base, TASK_NAME)
    hashes["task_sha256"] = snapshot_file(args.task, task_copy)
    args.task = task_copy
    product_dir = os.path.dirname(args.product)
    copies = {}
    for name in PRODUCT_FILES:
        copies[name] = snapshot_file(os.path.join(product_dir, name), os.path.join(base, "product", name))
    args.product = os.path.join(base, "product", "product.toml")
    hashes["product_toml_sha256"] = copies["product.toml"]
    hashes["policy_sha256"] = copies["policy.toml"]
    hashes["expected_tests_sha256"] = copies["expected-tests.json"]
    hashes["expected_tests_previous_sha256"] = copies["expected-tests.previous.json"]
    approvals_copy = os.path.join(base, APPROVALS_NAME)
    hashes["approvals_sha256"] = snapshot_approvals(args.approvals, approvals_copy)
    if args.approvals is not None:
        args.approvals = approvals_copy
    _snapshot_trust_files(args, base, hashes)
    return hashes


def _snapshot_trust_files(args, base, hashes):
    """T071: copy the signers file and the gate order into `<base>`, hash the copies, and point
    `args.allowed_signers` and `args.order_file` at them; every reader in a grade uses only those."""
    sources = {"allowed_signers": getattr(args, "allowed_signers", None) or approval_args.DEFAULT_ALLOWED_SIGNERS,
               "order.txt": grade_context.ORDER_FILE}
    for name, source in sources.items():
        copy = os.path.join(base, name)
        digest = snapshot_file(source, copy)
        if digest is None:
            raise InternalError("cannot snapshot %s (%s)" % (name, source))
        hashes[{"allowed_signers": "allowed_signers_sha256", "order.txt": "order_sha256"}[name]] = digest
    args.allowed_signers = os.path.join(base, "allowed_signers")
    args.order_file = os.path.join(base, "order.txt")


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


# ---------------------------------------------------------------- facts from the grade itself

def _pin_after(text, name):
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
    return (jsonio.sha256_hex(buck), _pin_after(text, "llvm"), _pin_after(text, "sysroot"), version)


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
    for key in sorted(INPUT_KEYS - OPTIONAL_KEYS):
        value = inputs.get(key)
        if key in ("gate_clean", "uncached"):
            ok = isinstance(value, bool)
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
    return bad


# ---------------------------------------------------------------- rigor verify

def check_verdict(data, signature_path, allowed_signers, expect, require_uncached=False):
    """Reasons this verdict must not be trusted as a PASS; an empty list means it can be.

    Order: the signature over the exact bytes, then the document, `core_sha256` recomputed from
    `core`, then the inputs and the expectations of the caller.
    """
    if not os.path.isfile(signature_path):
        return ["no signature file %s" % signature_path]
    if not approvals.signature_is_valid(data, signature_path, allowed_signers, VERDICT_NAMESPACE):
        return ["signature is not valid for an allowed signer in namespace %s" % VERDICT_NAMESPACE]
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        return ["verdict is not valid JSON: %s" % exc]
    if not isinstance(document, dict) or set(document) != {"core", "core_sha256", "metadata"}:
        return ["verdict has the wrong shape"]
    core = document["core"]
    if not isinstance(core, dict):
        return ["core is not an object"]
    if document["core_sha256"] != jsonio.sha256_hex(jsonio.canonical_dumps(core)):
        return ["core_sha256 does not match core"]
    problems = []
    if core.get("overall") != _PASS:
        problems.append("overall is %r, not PASS" % (core.get("overall"),))
    inputs = core.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != INPUT_KEYS:
        return problems + ["core has no well-formed inputs"]
    problems.extend("input %s is missing or malformed" % key for key in missing_inputs(inputs))
    if inputs["gate_clean"] is not True:
        problems.append("the gate tree was dirty")
    if core.get("uncached") != inputs["uncached"]:
        problems.append("core.uncached disagrees with inputs.uncached")
    if require_uncached and inputs["uncached"] is not True:
        problems.append("not an --uncached grade")
    for option, key in (("head", "head"), ("gate", "gate_sha"), ("policy_sha", "policy_sha256")):
        wanted = expect.get(option)
        if wanted is not None and inputs[key] != wanted:
            problems.append("%s is %s, expected %s" % (key, inputs[key], wanted))
    wanted = expect.get("witness_sha")
    if wanted is not None and inputs["witness_sha256"] is None:
        problems.append("witness_sha256 is null (graded without --witness), expected %s" % wanted)
    elif wanted is not None and inputs["witness_sha256"] != wanted:
        problems.append("witness_sha256 is %s, expected %s" % (inputs["witness_sha256"], wanted))
    wanted = expect.get("perf_sha")
    if wanted == NO_PERF and inputs["perf_sha256"] is not None:
        problems.append("perf_sha256 is %s, expected none (graded without --perf)" % inputs["perf_sha256"])
    elif wanted not in (None, NO_PERF) and inputs["perf_sha256"] is None:
        problems.append("perf_sha256 is null (graded without --perf), expected %s" % wanted)
    elif wanted not in (None, NO_PERF) and inputs["perf_sha256"] != wanted:
        problems.append("perf_sha256 is %s, expected %s" % (inputs["perf_sha256"], wanted))
    return problems


def run_verify(args):
    data = jsonio.read_bytes(args.verdict)
    signature = args.signature or args.verdict + ".sig"
    expect = {"head": args.expect_head, "gate": args.expect_gate,
              "policy_sha": args.expect_policy_sha, "witness_sha": args.expect_witness_sha,
              "perf_sha": args.expect_perf_sha}
    problems = check_verdict(data, signature, args.allowed_signers, expect, args.require_uncached)
    for problem in problems:
        print("rigor verify: REJECTED: %s" % problem)
    if problems:
        return EXIT_FAIL
    print("rigor verify: OK (signed PASS, core_sha256 %s)" % jsonio.sha256_hex(
        jsonio.canonical_dumps(jsonio.strict_loads(data)["core"])))
    return EXIT_PASS


def add_verify_parser(subparsers):
    parser = subparsers.add_parser(
        "verify", allow_abbrev=False,
        help="accept a grade verdict only if it is a signed, clean-gate PASS that matches expectations")
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--signature", help="default: <verdict>.sig")
    parser.add_argument("--allowed-signers", required=True,
                        help='ssh allowed_signers file whose lines allow namespace "%s"' % VERDICT_NAMESPACE)
    parser.add_argument("--expect-head", help="full sha of the head the verdict must be about")
    parser.add_argument("--expect-gate", help="full sha of the gate commit that must have graded it")
    parser.add_argument("--expect-policy-sha", help="sha256 of the policy.toml it must have used")
    parser.add_argument("--expect-witness-sha",
                        help="witness_sha256 of the witness bundle it must have been graded with; "
                             "a verdict graded without --witness is rejected")
    parser.add_argument("--expect-perf-sha",
                        help="perf_sha256 of the perf bundle it must have been graded with, or `none` for a "
                             "grade without --perf; a verdict graded without --perf is rejected for a sha")
    parser.add_argument("--require-uncached", action="store_true")
    parser.set_defaults(handler=run_verify, gate_id=None)

