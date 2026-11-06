"""The witness gates of `rigor grade` (P002, T039): `witness-tests` and `mutants-witness`.

The witness is the gate-held implementation the tests are judged against (docs/witness.md). Both gates
judge the modules W (`witness_scope.scope`, from the head's layout and the paths changed in `merge_base..head`):

* `witness-tests` assembles the witness tree (`<work>/tree-witness`: the head with the witness bundle's
  files in place of the impl paths of W), builds it in both modes and requires every expected test to pass
  there. Its own Buck2 daemon is shared with the next gate and killed at the end of `mutants-witness`
  (and again by `rigor grade`'s `finally`).
* `mutants-witness` mutates the witness of the modules in W (the same generator, tests and rules as the
  head's `mutants`) and requires zero survivors at L3 and above. Approvals use their own kind.

Both are applicable only when W holds a module with a bundle entry; otherwise they pass with info
`witness-scope`. A witness byte-identical to the head is the head: its test results and mutants are reused
(info `witness-equals-head`, zero actions). No finding carries source text of the witness (Q1, point 4):
mutant findings lose `original`/`replacement`, and compiler output of a failed witness build stays out of
the metadata.
"""

import os
from argparse import Namespace
from dataclasses import dataclass

from rigor_lib import approval_args, approvals, contract, gitrun, grade_build, grade_context, grade_mutants
from rigor_lib import grade_policy, grade_steps, jsonio, tests_gate, witness_scope
from rigor_lib import mutants_gate as rigor_mutants
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, GateResult, finding

TESTS_ID = "witness-tests"
MUTANTS_ID = "mutants-witness"
STATE_ATTR = "witness_state"   # set on the Grading by `witness-tests` for `mutants-witness`
STRICT_LEVELS = rigor_mutants.STRICT_LEVELS
MUTANT_RENAMES = {"survived-mutant": "witness-survived-mutant", "survivor": "witness-survivor"}
TEST_RENAMES = {"test-not-pass": "witness-test-not-pass"}
REDACTED_FIELDS = ("original", "replacement")


@dataclass
class State:
    """What `witness-tests` hands to `mutants-witness`."""
    judged: list          # the modules of W that have a bundle entry (sorted)
    layout: object        # grade_mutants.Layout of the head
    levels: dict
    run: object           # grade_build.TreeRun of the witness tree, or None when nothing was judged
    equals_head: bool     # the witness tree has exactly the head's product files


def _severity(level):
    return SEVERITY_ERROR if level in STRICT_LEVELS else SEVERITY_INFO


def _changed_paths(g):
    """Paths that differ between the merge base and the head, as `git diff --name-only` lists them."""
    base = gitrun.merge_base(g.src, g.base, g.head)
    found = []
    for entry in gitrun.changed_entries(g.src, base, g.head):
        try:
            found.append(entry.path.decode("utf-8"))
        except UnicodeDecodeError:
            continue  # never copied into a tree; the contract gate reports it
    return sorted(set(found))


def _head_layout(g):
    """The layout of the head tree. The head's daemon is stopped again: `witness-tests` has its own tree."""
    try:
        return grade_mutants.read_layout(grade_build.TreeRun(g.tree, g.work))
    finally:
        grade_context.kill_daemon(g.tree)


def _head_manifest_sha(g):
    """The sha256 the `assemble` gate committed to for the head's product files."""
    path = os.path.join(g.results, "assemble.json")
    document = jsonio.strict_loads(jsonio.read_bytes(path))
    shas = [f["sha256"] for f in document["findings"] if f["rule"] == "product-manifest"]
    if len(shas) != 1:
        raise InternalError("assemble.json has no single product-manifest")
    return shas[0]


def _expected_path(g):
    path = os.path.join(os.path.dirname(g.args.product), "expected-tests.json")
    if not os.path.isfile(path):
        raise InternalError("missing %s" % path)
    return path


def _judge_tests(g, directories):
    """`rigor tests` over the results of each mode, with the witness rule names and the mode added."""
    found = []
    for mode in grade_context.MODES:
        result = tests_gate.run(Namespace(
            results=directories[mode], expected=_expected_path(g), previous=None,
            approvals=g.args.approvals, repo=g.src, head=g.head,
            allowed_signers=approval_args.DEFAULT_ALLOWED_SIGNERS))
        found.extend(dict(item, rule=TEST_RENAMES.get(item["rule"], item["rule"]), mode=mode)
                     for item in result.findings)
    return found


def _build_findings(result):
    """Findings of the build step, as `witness-build-failed` (the original rule is `kind`)."""
    return [finding("witness-build-failed", **{k: v for k, v in item.items() if k not in ("rule", "severity")},
                    kind=item["rule"]) for item in result.findings]


def _without_compiler_output(metadata):
    """Build metadata without `stderr_tail`: diagnostics quote the lines of the witness."""
    clean = {}
    for key, value in metadata.items():
        if key == "stderr_tail":
            continue
        clean[key] = _without_compiler_output(value) if isinstance(value, dict) else value
    return clean


def _stop(g, state_run, result):
    """Stop the witness tree's daemon when nothing more will run on it."""
    if state_run is not None and result.status != "PASS":
        grade_context.kill_daemon(state_run.tree)
    return result


def witness_tests_gate(g):
    if g.status.get("assemble") != "PASS" or g.status.get("buckfiles") != "PASS":
        return None  # no trustworthy layout
    role = contract.load_contract(g.args.task).role
    if role == contract.ROLE_TEST_AUTHOR:
        raise InternalError("role test-author needs T041")
    path = grade_policy.policy_path(g)
    levels = grade_policy.load_levels(path)
    mapping, found = witness_scope.impl_map(grade_policy.load_document(path), levels)
    layout = _head_layout(g)
    scope = witness_scope.scope(role, _changed_paths(g), layout, mapping, levels)
    listed = g.witness.modules if g.witness is not None else {}
    judged = [label for label in scope if label in listed]
    found.append(finding("witness-scope", severity=SEVERITY_INFO, role=role, modules=scope, judged=judged))
    for label in scope:
        if label not in listed:
            found.append(finding("witness-missing", severity=_severity(levels[label]), module=label,
                                 level=levels[label]))
    metadata = {"role": role, "scope": scope, "judged": judged}
    setattr(g, STATE_ATTR, State(judged, layout, levels, None, False))
    if not judged or any(item["severity"] == SEVERITY_ERROR for item in found):
        return GateResult(TESTS_ID, found, metadata)  # nothing to build, or already failed
    return _build_and_judge(g, mapping, judged, found, metadata)


def _build_and_judge(g, mapping, judged, found, metadata):
    state = getattr(g, STATE_ATTR)
    tree = os.path.join(g.work, grade_context.WITNESS_TREE)
    _, manifest, _ = grade_steps.assemble_tree(g, tree, (g.witness, {label: mapping[label] for label in judged}))
    manifest_sha = jsonio.sha256_hex(jsonio.canonical_dumps(manifest))
    found.append(finding("witness-manifest", severity=SEVERITY_INFO, sha256=manifest_sha))
    work = os.path.join(g.work, grade_context.WITNESS_WORK)
    os.makedirs(work)
    run = grade_build.TreeRun(tree, work, test_results=os.path.join(work, "test-results"),
                              mutants_reports=os.path.join(work, "mutants-reports"))
    state.run = run
    state.equals_head = manifest_sha == _head_manifest_sha(g) and set(g.built) == set(grade_context.MODES)
    metadata["manifest_sha256"] = manifest_sha
    if state.equals_head:
        # The witness is the head: its results are the head's (zero actions).
        found.append(finding("witness-equals-head", severity=SEVERITY_INFO))
        found.extend(_judge_tests(g, g.built))
        metadata.update(executed_actions=0, cached_actions=0, equals_head=True)
        return _stop(g, run, GateResult(TESTS_ID, found, metadata))
    built = grade_build.build_tree(run, g.args.uncached)
    metadata["build"] = _without_compiler_output(built.metadata)
    metadata["equals_head"] = False
    for counter in ("executed_actions", "cached_actions"):
        metadata[counter] = built.metadata.get(counter, 0)
    found.extend(_build_findings(built))
    if not built.findings:
        found.extend(_judge_tests(g, run.built))
    return _stop(g, run, GateResult(TESTS_ID, found, metadata))


def redact_finding(item):
    """A mutant finding without the text of the mutation (Q1, point 4)."""
    return {key: value for key, value in item.items() if key not in REDACTED_FIELDS}


def redact_summary(summary):
    """A per-module mutants summary without the replacement text of its survivors."""
    survivors = [{k: v for k, v in item.items() if k != "replacement"} for item in summary["survivors"]]
    return dict(summary, survivors=survivors)


def _renamed(item):
    return redact_finding(dict(item, rule=MUTANT_RENAMES.get(item["rule"], item["rule"])))


def _head_mutants(g, labels):
    """(findings, summaries) of the head's `mutants` result for `labels`, or None when it cannot stand in:
    it did not run to a judgement, did not cover every label, or used an approval (whose kind is the
    implementer's, not the witness's)."""
    path = os.path.join(g.results, "mutants.json")
    if not os.path.isfile(path):
        return None
    document = jsonio.strict_loads(jsonio.read_bytes(path))
    metadata = document["metadata"]
    summaries = metadata.get("modules")
    if not isinstance(summaries, dict) or metadata.get("approvals_used") != [] \
            or not set(labels) <= set(summaries):
        return None
    found = [_renamed(item) for item in document["findings"] if item.get("module") in labels]
    return found, {label: redact_summary(summaries[label]) for label in labels}


def mutants_witness_gate(g):
    state = getattr(g, STATE_ATTR, None)
    if g.status.get(TESTS_ID) != "PASS" or state is None:
        return None
    try:
        return _mutants(g, state)
    finally:
        if state.run is not None:
            grade_context.kill_daemon(state.run.tree)


def _mutants(g, state):
    found = [finding("witness-scope", severity=SEVERITY_INFO, modules=state.judged)]
    if not state.judged:
        return GateResult(MUTANTS_ID, found, {"modules": {}, "approvals_used": []})
    chosen = grade_mutants.plan(state.layout, state.levels)
    modules = [m for m in chosen.modules if m.label in state.judged]
    found.extend(_renamed(item) for item in chosen.findings if item.get("module") in state.judged)
    metadata = {"scope": state.judged, "modules": {}, "approvals_used": []}
    if not modules:
        return GateResult(MUTANTS_ID, found, metadata)
    reused = _head_mutants(g, [m.label for m in modules]) if state.equals_head else None
    if reused is not None:
        found.append(finding("witness-equals-head", severity=SEVERITY_INFO))
        found.extend(reused[0])
        metadata.update(modules=reused[1], executed_actions=0, cached_actions=0, equals_head=True)
        return GateResult(MUTANTS_ID, found, metadata)
    metadata["equals_head"] = False
    metadata["package_sha256"] = grade_mutants.write_package(state.run, modules)
    build_found, build_metadata, built = grade_mutants.build_reports(state.run, g.args.uncached, modules)
    found.extend(build_found)
    metadata.update(_without_compiler_output(build_metadata))
    metadata["targets"] = {m.label: grade_mutants.target_label(i, m) for i, m in enumerate(modules)}
    if built:
        judged, summaries, used = grade_mutants.judge(
            g, state.run, modules, built, approvals.KIND_WITNESS_EQUIVALENT_MUTANT, MUTANT_RENAMES)
        found.extend(redact_finding(item) for item in judged)
        metadata["modules"] = {label: redact_summary(s) for label, s in summaries.items()}
        metadata["approvals_used"] = used
    return GateResult(MUTANTS_ID, found, metadata)
