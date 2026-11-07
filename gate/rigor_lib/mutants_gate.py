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
killed), crash-kill-ratio (L3 and up, info in L2: a function with at least MIN_KILLS killed mutants more
than CRASH_RATIO_NUM/CRASH_RATIO_DEN of which were killed by a crash and not by a failed check: the tests
mostly check "does not crash"), baseline-red, harness-mismatch, missing-run, bad-results, module-not-in-policy,
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
# T078 / B31 (R003 G6): `crash-kill-ratio`. Calibrated on the 13 annas-c module reports (562 functions with a
# kill, 7668 kills, 205 of them crashes): 503 functions are below 0.1, the honest maximum with 4+ kills is 0.42
# (a heap allocator), and the next ones are 0.57 and up. A function is flagged when it has at least MIN_KILLS
# kills and more than CRASH_RATIO_NUM/CRASH_RATIO_DEN of them are `killed-crash` (a majority of crashes).
# Integer arithmetic. A function with no check kill at all (ratio 1) is `crash-only-function`, not this rule.
MIN_KILLS = 4
CRASH_RATIO_NUM = 1
CRASH_RATIO_DEN = 2


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


HEADERS_DIR = "buck-headers/"


def product_path(file):
    """The product-relative path of a source the compiler saw through Buck2's header tree
    (`buck-out/.../buck-headers/annas/src/internal.h` is `annas/src/internal.h`)."""
    if (file.startswith("buck-out/") or "/buck-out/" in file) and HEADERS_DIR in file:
        return file.rsplit(HEADERS_DIR, 1)[1]
    return file


PRODUCT_CELL = "root"
OTHER_TREES = ("third_party/", "external/")
SYSTEM_ROOTS = ("/usr/",)  # the system's headers; the toolchain's own live in `toolchains//` of buck-out
OUTPUT_KINDS = ("gen", "art")  # buck-out/v2/<kind>/<cell>/...


def label_package(label):
    return label.split("//", 1)[1].split(":", 1)[0]


def product_packages(labels):
    """The packages of the labels of the product's own modules (the root cell)."""
    return frozenset(label_package(label) for label in labels if label.startswith("//"))


def in_packages(path, packages):
    return any(path == package or path.startswith(package + "/") for package in packages)


def buck_out_cell(parts):
    """The cell of `buck-out/<version>/{gen,art}/<cell>/...`, or None for any other layout."""
    for index, part in enumerate(parts[:-1]):
        if part in OUTPUT_KINDS and 0 < index <= 2:
            return parts[index + 1]
    return None


def outside_product(file, packages):
    """True when a header is certainly not product code: of another cell (`gate//third_party/**`, the
    toolchain's: `buck-out/v2/{gen,art}/<cell>/...`), of a Buck2 header tree whose product-relative
    path is under no package of the product (`psa/crypto_struct.h`), under `third_party/` or
    `external/`, or an absolute path under the system's `/usr/`. An absolute path into `buck-out/`
    is classified as the relative one. Any other path, absolute ones included, stays reported
    (fail closed)."""
    if file.startswith("/"):
        if "/buck-out/" in file:
            return outside_product(file.split("/buck-out/", 1)[1].join(["buck-out/", ""]), packages)
        return file.startswith(SYSTEM_ROOTS)
    parts = file.split("/")
    if parts[0] == "buck-out":
        cell = buck_out_cell(parts)
        if cell is not None and cell != PRODUCT_CELL:
            return True
        if HEADERS_DIR in file:
            return not in_packages(product_path(file), packages)
        return False
    return file.startswith(OTHER_TREES)


def skipped_findings(report, level, packages=None):
    """A function the generator could not reach (made by a macro, or defined in a product header)
    is code the tests are never judged on: not allowed in L3. A header outside the product is not
    product code and is not reported."""
    packages = product_packages([report.label]) if packages is None else packages
    found = []
    for source in report.sources:
        for name, file, reason in source.skipped:
            if reason == "header" and outside_product(file, packages):
                continue
            found.append(finding("unmutated-function", module=report.label, source=source.file,
                                 function=name, file=product_path(file), reason=reason,
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


def crash_ratio_findings(report, level, verdicts):
    """B31: a function whose kills are mostly crashes, not failed checks. Counts follow `function_findings`
    (a duplicate counts with the verdict of its original). Only functions with a check kill are judged here."""
    by_id = {v.mutant.id: v.verdict for v in verdicts}
    counts = {}
    for verdict in verdicts:
        kind = by_id[verdict.of] if verdict.of else verdict.verdict
        if kind in ("killed-assert", "killed-crash"):
            pair = counts.setdefault((verdict.mutant.file, verdict.mutant.function), [0, 0])
            pair[kind == "killed-crash"] += 1
    found = []
    for (file, function), (asserts, crashes) in sorted(counts.items()):
        kills = asserts + crashes
        if asserts and kills >= MIN_KILLS and crashes * CRASH_RATIO_DEN > kills * CRASH_RATIO_NUM:
            found.append(finding("crash-kill-ratio", module=report.label, file=file, function=function,
                                 asserts=asserts, crashes=crashes, ratio="%.3f" % (crashes / kills),
                                 threshold="%d/%d" % (CRASH_RATIO_NUM, CRASH_RATIO_DEN), min_kills=MIN_KILLS,
                                 severity="error" if level in STRICT_LEVELS else SEVERITY_INFO))
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
            "survivors": survivors, "tce": mutants_verdict.tce_counts(report, verdicts)}


def module_findings(report, level, approval_set, used, approval_kind=approvals.KIND_EQUIVALENT_MUTANT, packages=None):
    """(findings, summary) for one report."""
    found, baseline_ids = mutants_verdict.baseline_findings(report, level)
    verdicts, problems = mutants_verdict.derive(report, baseline_ids)
    found.extend(problems)
    found.extend(blindness_findings(report, verdicts))
    found.extend(unviable_findings(report, level, verdicts))
    found.extend(skipped_findings(report, level, packages))
    found.extend(hidden_findings(report, level))
    found.extend(survivor_findings(report, level, verdicts, approval_set, used, approval_kind))
    if level in STRICT_LEVELS:
        found.extend(function_findings(report, verdicts))
    found.extend(crash_ratio_findings(report, level, verdicts))
    return found, module_summary(report, verdicts)


def run(args, approval_kind=approvals.KIND_EQUIVALENT_MUTANT):
    reports = mutants_report.load_reports_dir(args.results)
    levels = load_policy(args.policy)
    approval_set = approval_args.load_from_args(args)
    used = set()
    found = list(approval_set.problems)
    summaries = {}
    packages = product_packages(levels)
    for label in sorted(reports):
        if label not in levels:
            found.append(finding("module-not-in-policy", module=label))
            continue
        module, summaries[label] = module_findings(reports[label], levels[label], approval_set, used, approval_kind, packages)
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
