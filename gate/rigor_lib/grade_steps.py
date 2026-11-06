"""The gates of `rigor grade` that do not run Buck2. Each takes a Grading, returns a GateResult
(or None when its input does not exist, which the verdict reports as NOT_RUN)."""

import os
from argparse import Namespace

from rigor_lib import approval_args, contract, gitrun, grade_context, grade_tree, jsonio, paths
from rigor_lib import product_layout, suppressions, tests_gate
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

_PLAIN_FILE_MODES = ("100644", "100755")


def clone_gate(g):
    grade_tree.clone(g.args.product_repo, g.src)
    g.base = gitrun.resolve_commit(g.src, g.args.base)
    g.head = gitrun.resolve_commit(g.src, g.args.head)
    merge_base = gitrun.merge_base(g.src, g.base, g.head)
    grade_tree.checkout_detached(g.src, g.head)
    return GateResult("clone", [], {"base": g.base, "head": g.head, "merge_base": merge_base})


def contract_gate(g):
    return contract.run(Namespace(repo=g.src, base=g.base, head=g.head, contract=g.args.task))


def suppressions_gate(g):
    return suppressions.run(Namespace(
        repo=g.src, base=g.base, head=g.head, approvals=g.args.approvals,
        allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS))


def _product_entry_findings(g, entry, manifest):
    """Copy one product file into the tree if the layout allows it; return its findings."""
    try:
        text = entry.path.decode("utf-8")
    except UnicodeDecodeError:
        return [finding("bad-path", path=paths.display_path(entry.path), reason="not UTF-8")]
    reason = paths.unsafe_path_reason(text)
    if reason is not None:
        return [finding("bad-path", path=text, reason=reason)]
    action = product_layout.classify(g.product, text)
    if action == product_layout.EXCLUDED_BY_GATE:
        return [finding("ignored-by-gate", severity=SEVERITY_INFO, path=text)]
    if action != product_layout.COPY:
        return []
    if entry.mode not in _PLAIN_FILE_MODES:
        return [finding("unsupported-entry", path=text, mode=entry.mode)]
    mode = 0o755 if entry.mode == "100755" else 0o644
    manifest[text] = grade_tree.write_file(g.tree, text, grade_tree.read_blob(g.src, entry), mode)
    return []


def assemble_gate(g):
    os.makedirs(g.tree)
    gate_files, gate_buckconfig = grade_tree.copy_gate(grade_context.GATE_ROOT, g.gate_sha, g.tree)
    manifest = {}
    found = []
    for entry in grade_tree.list_tree(g.src, g.head):
        found.extend(_product_entry_findings(g, entry, manifest))
    product_sha = jsonio.sha256_hex(jsonio.canonical_dumps(manifest))
    # The verdict commits to exactly which product files were built.
    found.append(finding("product-manifest", severity=SEVERITY_INFO, sha256=product_sha))
    generated = {".buckconfig": grade_tree.generated_buckconfig(gate_buckconfig), ".buckroot": b""}
    full = dict(gate_files)
    for name, data in generated.items():
        full[name] = grade_tree.write_file(g.tree, name, data, 0o644)
    full.update(manifest)
    metadata = {"gate_sha": g.gate_sha, "product_files": len(manifest),
                "manifest": [[path, full[path]] for path in sorted(full)]}
    return GateResult("assemble", found, metadata)


def tests_gate_for(mode):
    """The `tests` gate over one mode's results, registered as `tests-<mode>`."""
    def gate(g):
        directory = g.built.get(mode)
        if directory is None:
            return None  # the build did not produce clean results for this mode
        product_dir = os.path.dirname(g.args.product)
        expected = os.path.join(product_dir, "expected-tests.json")
        previous = os.path.join(product_dir, "expected-tests.previous.json")
        if not os.path.isfile(expected):
            raise InternalError("missing %s" % expected)
        result = tests_gate.run(Namespace(
            results=directory, expected=expected,
            previous=previous if os.path.isfile(previous) else None,
            approvals=g.args.approvals, repo=g.src, head=g.head,
            allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS))
        return GateResult("tests-" + mode, result.findings, result.metadata)
    return gate
