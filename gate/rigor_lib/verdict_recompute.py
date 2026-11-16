"""What `rigor verify` recomputes without building (U30 fix-up): bindings of a verdict checked against their sources.

- From the gate commit `inputs.gate_sha` in the gate repository: `order_sha256` and the gate order, `toolchain_buck_sha256`
  and its LLVM and sysroot pins, `buck2_sha256`, and `buckconfig_sha256` (the grading tree's generated `.buckconfig`).
- From the product directory (`inputs.product_dir` at that commit, or `--product-dir` for a product directory outside the
  gate checkout): every product configuration file the grade reads (`verdict_inputs.PRODUCT_FILE_KEYS`).
- From `--approvals DIR`: `approvals_sha256`, and each approval listed in force against its file.
Every function returns a list of problems (empty: consistent); none raises for a mismatch.
"""

import os

from rigor_lib import approvals, gitrun, grade_tree, jsonio, verdict, verdict_inputs
from rigor_lib.errors import InternalError

_GATE_FILES = ("gate/order.txt", "toolchains/BUCK", "tools/buck2.version", ".buckconfig")


def gate_file(gate_repo, gate_sha, rel_path):
    """Bytes of `rel_path` at the gate commit, or None if it is not a file there."""
    try:
        return gitrun.run_git(gate_repo, ["cat-file", "blob", "%s:%s" % (gate_sha, rel_path)])
    except InternalError:
        return None


def gate_bindings(gate_repo, gate_sha):
    """((expected input values, gate order), None), or (None, problem) when the commit or a file is missing."""
    if not gitrun.commit_exists(gate_repo, gate_sha):
        return None, "gate_sha %s is not a commit of the gate repository %s" % (gate_sha, gate_repo)
    files = {}
    for rel in _GATE_FILES:
        files[rel] = gate_file(gate_repo, gate_sha, rel)
        if files[rel] is None:
            return None, "gate revision %s has no %s" % (gate_sha, rel)
    try:
        text = files["toolchains/BUCK"].decode("utf-8")
        expected = {"order_sha256": jsonio.sha256_hex(files["gate/order.txt"]),
                    "toolchain_buck_sha256": jsonio.sha256_hex(files["toolchains/BUCK"]),
                    "llvm_sha256": verdict_inputs.pin_after(text, "llvm"),
                    "sysroot_sha256": verdict_inputs.pin_after(text, "sysroot"),
                    "buck2_sha256": files["tools/buck2.version"].decode("ascii").strip(),
                    "buckconfig_sha256": jsonio.sha256_hex(grade_tree.generated_buckconfig(files[".buckconfig"]))}
        order = verdict.parse_order(files["gate/order.txt"])
    except (UnicodeDecodeError, InternalError) as exc:
        return None, "gate revision %s: %s" % (gate_sha, exc)
    return (expected, order), None


def _gate_list_problems(core, order, gate_sha):
    gates = core.get("gates")
    if not isinstance(gates, list) or not all(isinstance(entry, dict) for entry in gates):
        return ["core.gates is not a list of objects"]
    if [entry.get("id") for entry in gates] != order:
        return ["the gate list is not the gate order of revision %s (a partial or reordered grade)" % gate_sha]
    if not all(entry.get("status") == verdict.STATUS_PASS for entry in gates):
        return ["overall is PASS but a gate is not"]
    return []


def check_gate(core, inputs, gate_repo):
    """Problems with the gate list and the gate-owned inputs against the gate commit the verdict names."""
    found, problem = gate_bindings(gate_repo, inputs["gate_sha"])
    if problem is not None:
        return [problem]
    expected, order = found
    problems = ["%s is %s, but gate revision %s gives %s" % (key, inputs[key], inputs["gate_sha"], value)
                for key, value in sorted(expected.items()) if inputs[key] != value]
    return problems + _gate_list_problems(core, order, inputs["gate_sha"])


def _dir_file_sha(directory, name):
    """sha256 of `directory/name` as the grade's snapshot sees it (a symlink or a non-file is absent)."""
    path = os.path.join(directory, name)
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    return jsonio.sha256_hex(jsonio.read_bytes(path))


def product_shas(inputs, gate_repo, product_dir):
    """({input key: expected sha or None}, None), or (None, problem) when the source cannot be chosen."""
    if inputs["product_dir"] is None and product_dir is None:
        return None, ("the grade read its product files from outside the gate checkout: pass --product-dir "
                      "with the same directory")
    if inputs["product_dir"] is not None and product_dir is not None:
        return None, ("the grade read its product files from the gate's %s: --product-dir must not be given"
                      % inputs["product_dir"])
    expected = {}
    for name, key in sorted(verdict_inputs.PRODUCT_FILE_KEYS.items()):
        if product_dir is not None:
            expected[key] = _dir_file_sha(product_dir, name)
        else:
            data = gate_file(gate_repo, inputs["gate_sha"], "%s/%s" % (inputs["product_dir"], name))
            expected[key] = None if data is None else jsonio.sha256_hex(data)
    return expected, None


def check_product(inputs, gate_repo, product_dir):
    """Problems with the product configuration bindings: a raised baseline or an edited policy shows here."""
    expected, problem = product_shas(inputs, gate_repo, product_dir)
    if problem is not None:
        return [problem]
    source = product_dir if product_dir is not None else "%s at %s" % (inputs["product_dir"], inputs["gate_sha"])
    return ["%s is %s, but %s gives %s" % (key, inputs[key], source, value)
            for key, value in sorted(expected.items()) if inputs[key] != value]


def _listed_problem(directory, entry):
    path = os.path.join(directory, entry["stem"] + ".json")
    if os.path.islink(path) or not os.path.isfile(path):
        return "approval %s is listed in force but has no file in %s" % (entry["stem"], directory)
    data = jsonio.read_bytes(path)
    parsed = approvals.parse_document(data, entry["stem"])
    if jsonio.sha256_hex(data) != entry["stem"] or parsed is None:
        return "approval %s: its file is not the approval of that hash" % entry["stem"]
    if (parsed.kind, parsed.scope, parsed.reason, parsed.repo_sha) != \
            (entry["kind"], entry["scope"], entry["reason"], entry["repo_sha"]):
        return "approval %s: the verdict lists it with other fields than its file" % entry["stem"]
    return None


def unlisted_in_dir(core, directory):
    """The well-formed approvals in `directory` (named by their hash) that `core` does not list in force.

    One-directional by design: whether such an approval applied (its `repo_sha` an ancestor of the head) needs the
    product repository, which `verify` does not read, so these are reported, never rejected."""
    if not os.path.isdir(directory):
        return []
    in_force = core.get("approvals", {}).get("in_force")
    listed = {entry.get("stem") for entry in in_force if isinstance(entry, dict)} if isinstance(in_force, list) else set()
    found = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not name.endswith(".json") or os.path.islink(path) or not os.path.isfile(path):
            continue
        stem, data = name[:-len(".json")], jsonio.read_bytes(path)
        parsed = approvals.parse_document(data, stem)
        if parsed is not None and jsonio.sha256_hex(data) == stem and stem not in listed:
            found.append(parsed)
    return found


def check_approvals_dir(core, inputs, directory):
    """Problems with `approvals_sha256` and each approval in force against the directory `--approvals` names."""
    if not os.path.isdir(directory):
        return ["--approvals %s is not a directory" % directory]
    digest = verdict_inputs.approvals_digest(directory)
    problems = []
    if inputs["approvals_sha256"] != digest:
        problems.append("approvals_sha256 is %s, but %s gives %s" % (inputs["approvals_sha256"], directory, digest))
    for entry in core["approvals"]["in_force"]:
        problem = _listed_problem(directory, entry)
        if problem is not None:
            problems.append(problem)
    return problems
