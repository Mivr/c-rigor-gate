"""`rigor lane-mutants`: measure the mutants of chosen modules the way the grade does, from a lane's checkout (T123).

The grade and a lane used to measure the same mutants twice, the lane with a hand-written `c_mutants` target
in a scratch clone (other action keys), the grade again from scratch. This command builds the grade's tree from
a commit of the product (the same clone, layout, `assemble_tree`, layout query, `plan` and `write_package` of
`grade_mutants`), writes the grade's `gate-mutants/BUCK` entries for the chosen modules only (the name, attributes,
tests and their order of a module do not depend on the other modules), builds them on the RE farm with the pinned
Buck2 and judges the reports with `rigor mutants`' own code (`grade_mutants.judge`). The `mutant_run` and
`mutant_compile` actions are therefore the grade's, and the grade of the same sources answers them from the RE
action cache. Nothing is written to the product checkout: the work directory lives outside it.

Only committed files are measured (the grade grades commits): a checkout with uncommitted changes to tracked
files is refused. `--level` changes only the level the verdict is judged at (the actions do not depend on it).
Exit 0: no error finding for the chosen modules at their level; 1: some; 2: internal error.
"""

import argparse
import os
import re
from dataclasses import replace

from rigor_lib import grade_build, grade_context, grade_mutants, grade_policy, grade_steps, grade_tree
from rigor_lib import gitrun, mutants_report, mutants_verdict, product_layout
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_INFO
from rigor_lib.runner import EXIT_FAIL, EXIT_PASS

_ROOT_LABEL = re.compile(r"//[A-Za-z0-9_./+-]*(:[A-Za-z0-9_.+-]+)?")


def normalise(label):
    """`//pkg/mod` is `//pkg/mod:mod`, as in Buck2."""
    if not _ROOT_LABEL.fullmatch(label):
        raise InternalError("not a target label of the product: %r" % (label,))
    if ":" not in label:
        name = label.rstrip("/").rsplit("/", 1)[-1]
        if not name:
            raise InternalError("no package in %r" % (label,))
        return "%s:%s" % (label.rstrip("/"), name)
    return label


def select(modules, wanted, level):
    """The planned modules that were asked for, with the level the verdict is judged at (the BUCK entry
    does not carry it). A label that is no mutated module of the product is an error naming the choices."""
    by_label = {m.label: m for m in modules}
    missing = [label for label in wanted if label not in by_label]
    if missing:
        raise InternalError("not a mutated module (level L2+ with tests) of the product: %s; known: %s"
                            % (", ".join(missing), ", ".join(sorted(by_label)) or "none"))
    return [replace(by_label[label], level=level or by_label[label].level) for label in wanted]


def table(reports):
    """Lines of the mutant table: one per mutant, in report order, then the counts per module."""
    lines = []
    for label in sorted(reports):
        report = reports[label]
        _, baseline_ids = mutants_verdict.baseline_findings(report)
        verdicts, _ = mutants_verdict.derive(report, baseline_ids)
        counts = {}
        for item in verdicts:
            m = item.mutant
            counts[item.verdict] = counts.get(item.verdict, 0) + 1
            lines.append("%-14s %-12s %s:%d  %s  %s: %s -> %s" % (
                item.verdict, label, m.file, m.line, m.id, m.function, m.original, m.replacement))
        lines.append("%s: %d mutants, %s" % (label, len(verdicts), ", ".join(
            "%d %s" % (counts[name], name) for name in sorted(counts)) or "none"))
    return lines


def _dirty(repo):
    out = gitrun.run_git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=no"])
    return out != b""


def _grading(args, work, product):
    gate_sha, _ = grade_context.gate_checkout_state(True)
    work_args = argparse.Namespace(product=args.product, approvals=args.approvals, allowed_signers=args.allowed_signers,
                                   uncached=args.uncached, repo=None, head=None)
    return grade_context.Grading(
        args=work_args, product=product, gate_sha=gate_sha, work=work, src=os.path.join(work, "src"),
        tree=os.path.join(work, "tree"), results=os.path.join(work, "results"),
        test_results=os.path.join(work, "test-results"))


def _prepare(args):
    repo = os.path.realpath(args.repo)
    if args.head is None and _dirty(repo):
        raise InternalError("%s has uncommitted changes to tracked files: commit them (the grade grades commits)" % repo)
    work = os.path.abspath(args.work or os.path.join(os.environ.get("TMPDIR", "/var/tmp"), "lane-mutants",
                                                      os.path.basename(repo)))
    args.product = os.path.abspath(args.product)
    if args.approvals is not None:
        args.approvals = os.path.abspath(args.approvals)
    product = product_layout.load_product(args.product)
    g = _grading(args, work, product)
    grade_context.prepare_work(work)
    grade_context.seal_process_environment(work)   # also where Buck2 and git read HOME from
    grade_tree.clone(repo, g.src)
    g.head = gitrun.resolve_commit(g.src, args.head or "HEAD")
    grade_tree.checkout_detached(g.src, g.head)
    g.args.repo, g.args.head = g.src, g.head
    return g


def measure(g, wanted, level):
    """(reports dir, findings, summaries, build findings, metadata) of the chosen modules in a freshly assembled tree."""
    found, _, _ = grade_steps.assemble_tree(g, g.tree)
    if any(item.get("severity") != SEVERITY_INFO for item in found):
        raise InternalError("assembling the tree: %s" % [item for item in found if item.get("severity") != SEVERITY_INFO])
    run = grade_build.TreeRun(g.tree, g.work, mutants_reports=os.path.join(g.work, "mutants-reports"))
    chosen, shared = grade_mutants.build_plan(g, run)
    modules = select(chosen.modules, wanted, level)
    grade_mutants.write_package(run, modules, shared)
    build_found, metadata, built = grade_mutants.build_reports(run, g.args.uncached, modules)
    judged, summaries, _ = grade_mutants.judge(g, run, modules, built) if built else ([], {}, [])
    return run, build_found + judged, summaries, metadata, modules, built


def report(run, found, metadata, modules, built):
    names = {grade_mutants.target_label(m): m.label for m in modules}
    reports = mutants_report.load_reports_dir(run.mutants_reports)
    for line in table({names.get(label, label): value for label, value in reports.items()}):
        print(line)
    errors = [item for item in found if item.get("severity") != SEVERITY_INFO]
    for item in errors:
        print("finding %s" % {k: v for k, v in sorted(item.items())})
    print("mutant actions: %d executed, %d from the cache; modules built %d of %d" % (
        metadata["executed_actions"], metadata["cached_actions"], len(built), len(modules)))
    verdict = "FAIL" if errors or len(built) != len(modules) else "PASS"
    print("verdict at %s: %s" % (", ".join("%s %s" % (m.label, m.level) for m in modules), verdict))
    return EXIT_PASS if verdict == "PASS" else EXIT_FAIL


def run(args):
    g = _prepare(args)
    wanted = [normalise(label) for label in args.modules]
    try:
        run_, found, _, metadata, modules, built = measure(g, wanted, args.level)
        return report(run_, found, metadata, modules, built)
    finally:
        grade_context.kill_daemon(g.tree)


def add_parser(subparsers):
    parser = subparsers.add_parser("lane-mutants", allow_abbrev=False,
                                   help="measure the grade's mutant actions of chosen modules (shared cache)")
    parser.add_argument("modules", nargs="+", metavar="MODULE", help="//pkg:module (or //pkg for //pkg:pkg)")
    parser.add_argument("--product", required=True, help="products/<name>/product.toml (policy.toml beside it)")
    parser.add_argument("--repo", default=".", help="the product checkout (default: the current directory)")
    parser.add_argument("--head", help="commit to measure (default: HEAD; a checkout with uncommitted changes is refused)")
    parser.add_argument("--level", choices=grade_policy.LEVELS[1:], help="judge at this level (default: the policy's)")
    parser.add_argument("--work", help="work directory, outside the checkout (default: $TMPDIR/lane-mutants/<checkout>)")
    parser.add_argument("--uncached", action="store_true", help="build with --no-remote-cache")
    parser.add_argument("--approvals")
    parser.add_argument("--allowed-signers", default=os.path.join(grade_context.GATE_ROOT, "gate", "allowed_signers"))
    parser.set_defaults(handler=run)

