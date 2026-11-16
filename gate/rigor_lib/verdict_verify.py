"""`rigor verify`: accept a grade verdict only if it is a content-consistent clean-gate PASS (U30).

Nobody signs a verdict. `verify` checks what a verdict says against what can be recomputed without
trusting its author or building: the canonical sha256 of `core`, the shape of every bound input, the
bindings `verdict_recompute` recomputes (gate commit, product directory, approvals directory), the approvals
it counts, and the caller's expectations (head and gate commit are mandatory). It proves that the verdict's
bindings match those sources; the bindings that only running the grade can produce (gate statuses and
findings, `gate_clean`, `tier`, `uncached`, commits other than the head) are self-reported. It does not prove
who ran the grade. Anyone can grade again and compare `core_sha256`. See docs/grade.md ("`rigor verify`").
"""

import re

from rigor_lib.errors import InternalError
from rigor_lib import approvals, grade_context, grade_tier, jsonio, verdict_inputs, verdict_recompute
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS

_PASS = "PASS"
# A verdict written before U30 bound the signers file; it was meant to be read with its `.sig`.
LEGACY_SIGNED_KEY = "allowed_signers_sha256"
_APPROVAL_KEYS = {"kind", "scope", "reason", "repo_sha", "stem"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def parse_core(data):
    """(core, problems): the verdict's core if the document is well formed and its hash matches."""
    try:
        document = jsonio.strict_loads(data)
    except ValueError as exc:
        return None, ["verdict is not valid JSON: %s" % exc]
    if not isinstance(document, dict) or set(document) != {"core", "core_sha256", "metadata"}:
        return None, ["verdict has the wrong shape"]
    core = document["core"]
    if not isinstance(core, dict):
        return None, ["core is not an object"]
    if document["core_sha256"] != jsonio.sha256_hex(jsonio.canonical_dumps(core)):
        return None, ["core_sha256 does not match core"]
    return core, []


def _approval_entry_ok(entry):
    return (isinstance(entry, dict) and set(entry) == _APPROVAL_KEYS
            and all(isinstance(entry[k], str) and entry[k] for k in _APPROVAL_KEYS)
            and entry["kind"] in approvals.KINDS and _SHA256.fullmatch(entry["stem"]) is not None
            and _FULL_SHA.fullmatch(entry["repo_sha"]) is not None)


def check_approvals(core, inputs):
    """Problems with the count and list of approvals in force (the loosenings a reader must see)."""
    block = core.get("approvals")
    if not isinstance(block, dict) or set(block) != {"count", "in_force"}:
        return ["core has no well-formed approvals count"]
    listed = block["in_force"]
    if not isinstance(listed, list) or not all(_approval_entry_ok(entry) for entry in listed):
        return ["core.approvals.in_force is malformed"]
    stems = [entry["stem"] for entry in listed]
    problems = []
    if type(block["count"]) is not int or block["count"] != len(listed):
        problems.append("core.approvals.count does not match the approvals listed")
    if stems != sorted(set(stems)):
        problems.append("core.approvals.in_force is not sorted by stem without duplicates")
    if listed and inputs.get("approvals_sha256") is None:
        problems.append("approvals are listed in force but no approvals bundle is bound")
    return problems


def check_inputs(core, inputs, require_uncached, require_tier):
    """Problems with the bound inputs themselves (shape, clean gate, cache and tier)."""
    problems = ["input %s is missing or malformed" % key for key in verdict_inputs.missing_inputs(inputs)]
    if inputs["gate_clean"] is not True:
        problems.append("the gate tree was dirty")
    if core.get("uncached") != inputs["uncached"]:
        problems.append("core.uncached disagrees with inputs.uncached")
    if require_uncached and inputs["uncached"] is not True:
        problems.append("not an --uncached grade")
    if require_tier is not None and inputs["tier"] != require_tier:
        problems.append("tier is %s, expected %s" % (inputs["tier"], require_tier))
    return problems


def _expect_bundle(inputs, key, wanted, option):
    """A bundle the caller pins by sha: a grade without it is rejected, so is another bundle."""
    if wanted is None:
        return []
    if inputs[key] is None:
        return ["%s is null (graded without --%s), expected %s" % (key, option, wanted)]
    if inputs[key] != wanted:
        return ["%s is %s, expected %s" % (key, inputs[key], wanted)]
    return []


def check_expectations(inputs, expect):
    """Problems with what the caller said the verdict must be about."""
    problems = []
    wanted = expect.get("product_dir")
    if wanted is not None and inputs["product_dir"] != wanted:
        problems.append("product_dir is %s, expected %s" % (inputs["product_dir"], wanted))
    for option, key in (("head", "head"), ("gate", "gate_sha"), ("policy_sha", "policy_sha256"),
                        ("task_sha", "task_sha256"), ("sim_salt_id", "sim_salt_id"),
                        ("sim_spec_sha", "sim_spec_sha256")):
        wanted = expect.get(option)
        if wanted is not None and inputs[key] != wanted:
            problems.append("%s is %s, expected %s" % (key, inputs[key], wanted))
    problems += _expect_bundle(inputs, "witness_sha256", expect.get("witness_sha"), "witness")
    problems += _expect_bundle(inputs, "oracle_sha256", expect.get("oracle_sha"), "oracle")
    wanted = expect.get("perf_sha")
    if wanted == verdict_inputs.NO_PERF and inputs["perf_sha256"] is not None:
        problems.append("perf_sha256 is %s, expected none (graded without --perf)" % inputs["perf_sha256"])
    elif wanted != verdict_inputs.NO_PERF:
        problems += _expect_bundle(inputs, "perf_sha256", wanted, "perf")
    return problems


def check_verdict(data, expect, sources, require_uncached=False, require_tier=None):
    """Reasons this verdict must not be trusted as a PASS; an empty list means it can be.

    `sources`: {"gate_repo", "product_dir" (or None), "approvals" (or None)}. Order: the document and
    `core_sha256`, the inputs (a verdict of the signing gate is refused by name), the recomputed bindings,
    the approvals count, the caller's expectations."""
    core, problems = parse_core(data)
    if core is None:
        return problems
    if core.get("overall") != _PASS:
        problems.append("overall is %r, not PASS" % (core.get("overall"),))
    inputs = core.get("inputs")
    if isinstance(inputs, dict) and LEGACY_SIGNED_KEY in inputs:
        return problems + ["written by a gate that signed verdicts (inputs.%s): that format is no longer "
                           "accepted, grade again with this gate" % LEGACY_SIGNED_KEY]
    if not isinstance(inputs, dict) or set(inputs) != verdict_inputs.INPUT_KEYS:
        return problems + ["core has no well-formed inputs"]
    problems += check_inputs(core, inputs, require_uncached, require_tier)
    approval_problems = check_approvals(core, inputs)
    if not problems:   # every binding is well formed: recompute what can be recomputed
        problems += verdict_recompute.check_gate(core, inputs, sources["gate_repo"])
        problems += verdict_recompute.check_product(inputs, sources["gate_repo"], sources["product_dir"])
        if sources["approvals"] is not None and not approval_problems:
            problems += verdict_recompute.check_approvals_dir(core, inputs, sources["approvals"])
    return problems + approval_problems + check_expectations(inputs, expect)


def verdict_tier(data):
    """The tier a verdict says it was graded at, or `unknown` when it does not say (or is not a verdict)."""
    try:
        tier = jsonio.strict_loads(data)["core"]["inputs"]["tier"]
    except (ValueError, KeyError, TypeError):
        return "unknown"
    return tier if tier in grade_tier.TIERS else "unknown"


def _inputs_of(data):
    try:
        inputs = jsonio.strict_loads(data)["core"]["inputs"]
    except (ValueError, KeyError, TypeError):
        return None
    return inputs if isinstance(inputs, dict) else None


def sim_lines(data):
    """`rigor verify` lines for the simulation inputs of a verdict (null as `none`); nothing for a document without inputs."""
    inputs = _inputs_of(data)
    if inputs is None:
        return []
    return ["rigor verify: %s %s" % (key, inputs.get(key) or "none")
            for key in ("sim_spec_sha256", "sim_salt_id", "sim_seed_digest")]


def product_dir_lines(data):
    """`rigor verify: product_dir <path>` (`none`: outside the gate checkout, the verifier supplies the files)."""
    inputs = _inputs_of(data)
    if inputs is None:
        return []
    return ["rigor verify: product_dir %s" % (inputs.get("product_dir") or "none")]


def unlisted_lines(data, directory):
    """Informational lines for approvals in `--approvals DIR` that the verdict does not list in force."""
    if directory is None:
        return []
    try:
        core = jsonio.strict_loads(data)["core"]
    except (ValueError, KeyError, TypeError):
        return []
    if not isinstance(core, dict) or not isinstance(core.get("approvals"), dict):
        return []
    return ["rigor verify: in %s, not listed in the verdict (their applicability is not checked here): %s %s %s"
            % (directory, a.kind, a.scope, a.stem) for a in verdict_recompute.unlisted_in_dir(core, directory)]


def approval_lines(data):
    """`rigor verify` lines: how many approvals (loosenings) the verdict counts in force, and each one."""
    try:
        block = jsonio.strict_loads(data)["core"]["approvals"]
        listed = [e for e in block["in_force"] if isinstance(e, dict)]
    except (ValueError, KeyError, TypeError):
        return []
    lines = ["rigor verify: approvals in force %d" % len(listed)]
    lines += ["rigor verify:   %s %s %s" % (e.get("kind"), e.get("scope"), e.get("stem")) for e in listed]
    return lines


def run_verify(args):
    data = jsonio.read_bytes(args.verdict)
    expect = {"head": args.expect_head, "gate": args.expect_gate,
              "policy_sha": args.expect_policy_sha, "witness_sha": args.expect_witness_sha,
              "perf_sha": args.expect_perf_sha, "oracle_sha": args.expect_oracle_sha, "sim_salt_id": args.expect_sim_salt_id,
              "sim_spec_sha": args.expect_sim_spec_sha, "task_sha": args.expect_task_sha}
    if args.product_dir is None and args.expect_product_dir is None:
        raise InternalError("--expect-product-dir is required unless --product-dir is given")
    expect["product_dir"] = args.expect_product_dir
    sources = {"gate_repo": args.gate_repo, "product_dir": args.product_dir, "approvals": args.approvals}
    problems = check_verdict(data, expect, sources, args.require_uncached, args.require_tier)
    print("rigor verify: tier %s" % verdict_tier(data))
    for line in product_dir_lines(data) + sim_lines(data) + approval_lines(data) + unlisted_lines(data, args.approvals):
        print(line)
    for problem in problems:
        print("rigor verify: REJECTED: %s" % problem)
    if problems:
        return EXIT_FAIL
    print("rigor verify: OK (consistent PASS, core_sha256 %s)" % jsonio.sha256_hex(
        jsonio.canonical_dumps(jsonio.strict_loads(data)["core"])))
    return EXIT_PASS


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "verify", allow_abbrev=False,
        help="accept a grade verdict only if it is a clean-gate PASS whose bindings match its head, gate commit and sources")
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--expect-head", required=True, help="full sha of the head the verdict must be about")
    parser.add_argument("--expect-gate", required=True, help="full sha of the gate commit that must have graded it")
    parser.add_argument("--gate-repo", default=grade_context.GATE_ROOT,
                        help="gate repository holding the verdict's gate_sha (default: this checkout); the gate "
                             "order, toolchain pins, generated .buckconfig and product files are recomputed from it")
    parser.add_argument("--product-dir", help="the product directory the grade used, when it lies outside the gate "
                                              "checkout (inputs.product_dir null); its files are recomputed")
    parser.add_argument("--approvals", metavar="DIR", help="the approvals directory the grade used: approvals_sha256 "
                                                           "and every approval in force are recomputed from it")
    parser.add_argument("--expect-task-sha", help="sha256 of the TASK.toml it must have been graded with")
    parser.add_argument("--expect-policy-sha", required=True, help="sha256 of the policy.toml it must have used")
    parser.add_argument("--expect-product-dir", help="the gate-relative product directory it must have been graded "
                                                     "with (products/<name>); required unless --product-dir is given")
    parser.add_argument("--expect-witness-sha",
                        help="witness_sha256 of the witness bundle it must have been graded with; "
                             "a verdict graded without --witness is rejected")
    parser.add_argument("--expect-oracle-sha",
                        help="oracle_sha256 of the oracle bundle it must have been graded with; "
                             "a verdict graded without --oracle is rejected")
    parser.add_argument("--expect-perf-sha",
                        help="perf_sha256 of the perf bundle it must have been graded with, or `none` for a "
                             "grade without --perf; a verdict graded without --perf is rejected for a sha")
    parser.add_argument("--expect-sim-salt-id", help="sim_salt_id (sha256 of the salt) the simulation must have run with")
    parser.add_argument("--expect-sim-spec-sha", help="sim_spec_sha256 of the sim.toml the grade must have used")
    parser.add_argument("--require-uncached", action="store_true")
    parser.add_argument("--require-tier", choices=grade_tier.TIERS,
                        help="reject a verdict graded at another tier (a merge-tier PASS is not a nightly one)")
    parser.set_defaults(handler=run_verify, gate_id=None)
