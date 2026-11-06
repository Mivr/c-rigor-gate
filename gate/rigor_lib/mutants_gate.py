"""`rigor mutants`: zero surviving mutants in L3 modules, and proof the generator was not blind.

Input is a directory of `c_mutants` reports (one `*.json` per module, see mutants_report) and a
gate-owned policy:

    [module."//core:core_mutants"]     # label of the c_mutants target
    level = "L3"                       # L3 and up: a survivor fails the gate; L2: survivors are reported

Levels L1 (not mutated, so never in this policy) to L5 exist; L3, L4 and L5 are equally strict here.

Findings: survived-mutant (L3; covered by an `equivalent-mutant` approval whose scope is the mutant
id), no-mutants (a source with functions but no mutants: the generator went blind), all-unviable,
unmutated-function (L3: a function made by a macro or defined in a product header, which no mutant
can reach; info in L2),
unviable-ratio (more than a quarter of the generated mutants did not compile: L3 and up; info in L2),
macro-hidden-code (L3: a function body uses a macro defined by the product, whose expansion no mutant
can reach; info in L2),
crash-only-function / no-assert-kill-function (L3 function whose mutants no check failure ever
killed), baseline-red, harness-mismatch, missing-run, bad-results, module-not-in-policy,
policy-module-without-report, no-reports. Survivors of L2 modules are info findings.
"""

import tomllib

from rigor_lib import approval_args, approvals, jsonio, mutants_report, mutants_verdict
from rigor_lib.errors import InternalError
from rigor_lib.facts_data import LABEL
from rigor_lib.findings import SEVERITY_INFO, GateResult, finding
from rigor_lib.runner import gate_handler

GATE_ID = "mutants"
LEVELS = ("L2", "L3", "L4", "L5")
STRICT_LEVELS = ("L3", "L4", "L5")
# B11: a module whose mutants mostly fail to compile has been shaped to escape mutation testing.
MAX_UNVIABLE_PERCENT = 25


def load_policy(path):
    """label -> level. Gate-owned, so any defect is exit 2."""
    try:
        document = tomllib.loads(jsonio.read_bytes(path).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalError("%s is not valid TOML: %s" % (path, exc)) from exc
    if set(document) != {"module"} or not isinstance(document["module"], dict):
        raise InternalError("policy: the only top-level table is [module.\"label\"]")
    levels = {}
    for label, table in document["module"].items():
        if not LABEL.fullmatch(label) or not isinstance(table, dict) or set(table) != {"level"} \
                or table["level"] not in LEVELS:
            raise InternalError("policy: module %r needs exactly level = \"L2\" or \"L3\"" % label)
        levels[label] = table["level"]
    return levels


def survivor_fields(label, mutant):
    return {"module": label, "id": mutant.id, "file": mutant.file, "line": mutant.line,
            "function": mutant.function, "operator": mutant.operator,
            "original": mutant.original, "replacement": mutant.replacement}


def blindness_findings(report, verdicts):
    found = []
    counts = {}
    for verdict in verdicts:
        counts[verdict.mutant.file] = counts.get(verdict.mutant.file, 0) + 1
    for source in report.sources:
        if source.functions and not counts.get(source.file):
            found.append(finding("no-mutants", module=report.label, file=source.file,
                                 functions=len(source.functions)))
    if not verdicts and not found:
        # A gate that mutates nothing must not pass: no source of this module produced a mutant.
        found.append(finding("no-mutants", module=report.label, file="*", functions=0))
    if verdicts and all(v.verdict == "unviable" for v in verdicts):
        found.append(finding("all-unviable", module=report.label, mutants=len(verdicts)))
    return found


def unviable_findings(report, level, verdicts):
    """More than 25 % of all generated mutants unviable (integer arithmetic, no rounding)."""
    unviable = sum(1 for v in verdicts if v.verdict == "unviable")
    if unviable * 100 <= MAX_UNVIABLE_PERCENT * len(verdicts) or unviable == len(verdicts):
        return []  # (all unviable has a finding of its own)
    return [finding("unviable-ratio", module=report.label, unviable=unviable, total=len(verdicts),
                    severity="error" if level in STRICT_LEVELS else SEVERITY_INFO)]


def skipped_findings(report, level):
    """A function the generator could not reach (made by a macro, or defined in a product header)
    is code the tests are never judged on: not allowed in L3."""
    found = []
    for source in report.sources:
        for name, file, reason in source.skipped:
            found.append(finding("unmutated-function", module=report.label, source=source.file,
                                 function=name, file=file, reason=reason,
                                 severity="error" if level in STRICT_LEVELS else SEVERITY_INFO))
    return found


def hidden_findings(report, level):
    """Code a macro of the product wrote inside a function the generator mutated (R002 F1): the
    mutants never touch it, so a backdoor there is invisible. Macros of the toolchain's headers
    (`NULL`, `bool`, `INT32_MAX`) are not reported by the generator. Not approvable."""
    found = []
    for source in report.sources:
        for function, macro, line, defined_in in source.hidden:
            found.append(finding("macro-hidden-code", module=report.label, file=source.file, line=line,
                                 function=function, macro=macro, defined_in=defined_in,
                                 severity="error" if level in STRICT_LEVELS else SEVERITY_INFO))
    return found


def function_findings(report, verdicts):
    """Every function with mutants needs a mutant that some test killed by a failed check. A
    duplicate counts with the verdict of the mutant it duplicates (the same object, the same run)."""
    by_id = {v.mutant.id: v.verdict for v in verdicts}
    by_function = {}
    for verdict in verdicts:
        key = (verdict.mutant.file, verdict.mutant.function)
        by_function.setdefault(key, set()).add(by_id[verdict.of] if verdict.of else verdict.verdict)
    found = []
    for (file, function), kinds in sorted(by_function.items()):
        if "killed-assert" in kinds or "survived" in kinds or "unrun" in kinds:
            continue  # survivors and unrun mutants are findings of their own
        rule = "crash-only-function" if "killed-crash" in kinds else "no-assert-kill-function"
        found.append(finding(rule, module=report.label, file=file, function=function))
    return found


def survivor_findings(report, level, verdicts, approval_set, used, approval_kind=approvals.KIND_EQUIVALENT_MUTANT):
    found = []
    for verdict in verdicts:
        if verdict.verdict != "survived":
            continue
        fields = survivor_fields(report.label, verdict.mutant)
        if level not in STRICT_LEVELS:
            found.append(finding("survivor", severity=SEVERITY_INFO, **fields))
            continue
        approval = approval_set.covering(approval_kind, verdict.mutant.id)
        if approval is None:
            found.append(finding("survived-mutant", **fields))
        else:
            used.add(approval.stem)
    return found


def module_summary(report, verdicts):
    verdict_counts = {name: 0 for name in mutants_verdict.VERDICTS}
    operators = {}
    for verdict in verdicts:
        verdict_counts[verdict.verdict] += 1
        operators[verdict.mutant.operator] = operators.get(verdict.mutant.operator, 0) + 1
    survivors = [{"id": v.mutant.id, "at": "%s:%d" % (v.mutant.file, v.mutant.line),
                  "operator": v.mutant.operator, "replacement": v.mutant.replacement}
                 for v in verdicts if v.verdict == "survived"]
    return {"total": len(verdicts), "verdicts": verdict_counts, "operators": operators,
            "survivors": survivors}


def module_findings(report, level, approval_set, used, approval_kind=approvals.KIND_EQUIVALENT_MUTANT):
    """(findings, summary) for one report."""
    found, baseline_ids = mutants_verdict.baseline_findings(report)
    verdicts, problems = mutants_verdict.derive(report, baseline_ids)
    found.extend(problems)
    found.extend(blindness_findings(report, verdicts))
    found.extend(unviable_findings(report, level, verdicts))
    found.extend(skipped_findings(report, level))
    found.extend(hidden_findings(report, level))
    found.extend(survivor_findings(report, level, verdicts, approval_set, used, approval_kind))
    if level in STRICT_LEVELS:
        found.extend(function_findings(report, verdicts))
    return found, module_summary(report, verdicts)


def run(args, approval_kind=approvals.KIND_EQUIVALENT_MUTANT):
    reports = mutants_report.load_reports_dir(args.results)
    levels = load_policy(args.policy)
    approval_set = approval_args.load_from_args(args)
    used = set()
    found = list(approval_set.problems)
    summaries = {}
    for label in sorted(reports):
        if label not in levels:
            found.append(finding("module-not-in-policy", module=label))
            continue
        module, summaries[label] = module_findings(reports[label], levels[label], approval_set, used, approval_kind)
        found.extend(module)
    for label in sorted(set(levels) - set(reports)):
        found.append(finding("policy-module-without-report", module=label))
    return GateResult(GATE_ID, found, {"modules": summaries, "approvals_used": sorted(used)})


def add_parser(subparsers):
    parser = subparsers.add_parser("mutants", allow_abbrev=False,
                                   help="zero surviving mutants in L3 modules")
    parser.add_argument("--results", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--out")
    approval_args.add_approval_arguments(parser, repo_and_head_optional=True)
    parser.set_defaults(handler=gate_handler(run), gate_id=GATE_ID)
