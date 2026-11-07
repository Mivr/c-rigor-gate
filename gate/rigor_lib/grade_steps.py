"""The gates of `rigor grade` that do not run Buck2. Each takes a Grading, returns a GateResult
(or None when its input does not exist, which the verdict reports as NOT_RUN)."""

import os
from argparse import Namespace

from rigor_lib import approval_args, contract, gitrun, grade_context, grade_tree, jsonio, paths
from rigor_lib import grade_policy, product_layout, stub_judge, suppressions, tests_gate, witness_bundle
from rigor_lib import witness_scope
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding

_PLAIN_FILE_MODES = ("100644", "100755")
EXPECTED_NAME = "expected-tests.json"
PREVIOUS_NAME = "expected-tests.previous.json"
NOT_APPLICABLE = "not-applicable"


def clone_gate(g):
    grade_tree.clone(g.args.product_repo, g.src)
    g.base = gitrun.resolve_commit(g.src, g.args.base)
    g.head = gitrun.resolve_commit(g.src, g.args.head)
    merge_base = gitrun.merge_base(g.src, g.base, g.head)
    grade_tree.checkout_detached(g.src, g.head)
    return GateResult("clone", [], {"base": g.base, "head": g.head, "merge_base": merge_base})


def contract_gate(g):
    result = contract.run(Namespace(repo=g.src, base=g.base, head=g.head, contract=g.args.task))
    check_witness_inputs(g)
    return result


def role(g):
    """The role of the task contract (P002 Terms), read from the snapshot every gate reads."""
    return contract.load_contract(g.args.task).role


def _product_input(g, name):
    return os.path.join(os.path.dirname(g.args.product), name)


def check_witness_inputs(g):
    """Exit 2 before any build for what the witness gates could never judge (P002 Q1, Q2).

    * role test-author needs `expected-tests.previous.json` (its new ids are `expected` minus that list;
      `{"ids": []}` for a new product): without it nothing says which tests must fail on the stubs;
    * a witness bundle is checked against the policy's impl paths and the product name.
    """
    if role(g) == contract.ROLE_TEST_AUTHOR and not os.path.isfile(_product_input(g, PREVIOUS_NAME)):
        raise InternalError("role test-author needs %s next to product.toml" % PREVIOUS_NAME)
    if g.witness is not None:
        document = grade_policy.load_document(grade_policy.policy_path(g))
        mapping, _ = witness_scope.impl_map(document, grade_policy.load_levels(grade_policy.policy_path(g)))
        witness_bundle.check(g.witness, g.product.name, mapping)


def _graded_entries(g):
    """The plain files of `head` that `assemble` copies into the tree (same layout test)."""
    graded = []
    for entry in grade_tree.list_tree(g.src, g.head):
        try:
            text = entry.path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if paths.unsafe_path_reason(text) is not None:
            continue
        if product_layout.classify(g.product, text) != product_layout.COPY:
            continue
        if entry.mode in _PLAIN_FILE_MODES:
            graded.append(entry)
    return graded


def suppressions_gate(g):
    return suppressions.run(Namespace(
        repo=g.src, base=g.base, head=g.head, approvals=g.args.approvals,
        allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS), _graded_entries(g))


def _product_entry_findings(g, tree, entry, manifest):
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
    manifest[text] = grade_tree.write_file(tree, text, grade_tree.read_blob(g.src, entry), mode)
    return []


def _witness_files(g, bundle, modules):
    """(head paths the witness replaces, the witness files that take their place) for the modules in
    `modules` ({label: impl globs}) that the bundle lists. A witness file the layout would not copy is a
    defect of the bundle (exit 2), not something to leave out silently."""
    head_paths = [entry.path.decode("utf-8") for entry in _graded_entries(g)]
    kept, files = witness_bundle.overlay(head_paths, bundle, modules)
    for item in files:
        if product_layout.classify(g.product, item.path) != product_layout.COPY:
            raise InternalError("witness file %s is not a file the layout copies" % item.path)
    return set(head_paths) - set(kept), files


def assemble_tree(g, tree, overlay=None):
    """Assemble a grading tree at `tree`: the gate files, the generated `.buckconfig` and every product file
    of the clone at `g.head` that the layout allows. Returns (findings, product manifest, full manifest).

    `overlay` is None for the head tree. For the witness tree it is (bundle, modules): the head files that
    match the impl globs of those modules are left out and the bundle's files are written instead (P002).
    """
    os.makedirs(tree)
    gate_files, gate_buckconfig = grade_tree.copy_gate(grade_context.GATE_ROOT, g.gate_sha, tree)
    skipped, witness_files = _witness_files(g, *overlay) if overlay is not None else (set(), ())
    manifest = {}
    found = []
    for entry in grade_tree.list_tree(g.src, g.head):
        if entry.path.decode("utf-8", "replace") in skipped:
            continue
        found.extend(_product_entry_findings(g, tree, entry, manifest))
    for item in witness_files:
        manifest[item.path] = grade_tree.write_file(tree, item.path, item.data, 0o644)
    product_sha = jsonio.sha256_hex(jsonio.canonical_dumps(manifest))
    # The verdict commits to exactly which product files were built.
    found.append(finding("product-manifest", severity=SEVERITY_INFO, sha256=product_sha))
    generated = {".buckconfig": grade_tree.generated_buckconfig(gate_buckconfig), ".buckroot": b""}
    full = dict(gate_files)
    for name, data in generated.items():
        full[name] = grade_tree.write_file(tree, name, data, 0o644)
    full.update(manifest)
    return found, manifest, full


def assemble_gate(g):
    found, manifest, full = assemble_tree(g, g.tree)
    g.product_paths = sorted(manifest)
    metadata = {"gate_sha": g.gate_sha, "product_files": len(manifest),
                "manifest": [[path, full[path]] for path in sorted(full)]}
    return GateResult("assemble", found, metadata)


def _expected_input(g):
    expected = _product_input(g, EXPECTED_NAME)
    if not os.path.isfile(expected):
        raise InternalError("missing %s" % expected)
    return expected


def tests_gate_for(mode):
    """The `tests` gate over one mode's results, registered as `tests-<mode>`.

    In role test-author the head is the stub commit, whose tests fail by design (old ones too, when a
    function they use was stubbed): presence, duplicates and parse problems of every expected id are
    judged, pass/fail is not (`tests_gate` `presence_only`); `witness-tests` judges every status on the
    witness tree and `tests-stub` the new ids on the stubs (P002 Q2)."""
    def gate(g):
        directory = g.built.get(mode)
        if directory is None:
            return None  # the build did not produce clean results for this mode
        expected = _expected_input(g)
        previous = _product_input(g, PREVIOUS_NAME)
        result = tests_gate.run(Namespace(
            results=directory, expected=expected,
            previous=previous if os.path.isfile(previous) else None,
            approvals=g.args.approvals, repo=g.src, head=g.head,
            allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS,
            presence_only=role(g) == contract.ROLE_TEST_AUTHOR))
        return GateResult("tests-" + mode, result.findings, result.metadata)
    return gate


def tests_stub_gate(g):
    """`tests-stub` (P002 Q2): in role test-author every new expected id fails on the stubs, in release
    and in san (`stub_judge`). It reads the head's results of both modes and builds nothing.

    Any other role: PASS with info `not-applicable`, whatever the build did (that role's head is not a
    stub commit). Role test-author: NOT_RUN unless both modes built clean."""
    current = role(g)
    if current != contract.ROLE_TEST_AUTHOR:
        return GateResult(stub_judge.GATE_ID, [finding(NOT_APPLICABLE, severity=SEVERITY_INFO, role=current)],
                          {"role": current})
    if any(g.built.get(mode) is None for mode in stub_judge.MODES):
        return None  # no clean results of both modes: nothing to judge
    previous = _product_input(g, PREVIOUS_NAME)
    if not os.path.isfile(previous):
        raise InternalError("role test-author needs %s next to product.toml" % PREVIOUS_NAME)
    parsed = {mode: stub_judge.parse_directory(g.built[mode]) for mode in stub_judge.MODES}
    result = stub_judge.judge(tests_gate.load_id_list(_expected_input(g)), tests_gate.load_id_list(previous),
                              parsed)
    return GateResult(stub_judge.GATE_ID, result.findings, dict(result.metadata, role=current))
