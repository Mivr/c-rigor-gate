"""Coverage report for a c_test built in the `cov` mode, produced entirely on RE.

Runs the instrumented test, merges the raw profile with the fetched llvm-profdata and
renders line, branch and MC/DC summaries with the fetched llvm-cov.
"""

def _cov_report_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.test[DefaultInfo].default_outputs[0]
    report = ctx.actions.declare_output("report.txt")
    detail = ctx.actions.declare_output("detail.txt")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -eu",
            'bin="$1"; profdata="$2"; cov="$3"; report="$4"; detail="$5"',
            'raw="$(dirname "$report")/test.profraw"',
            'merged="$(dirname "$report")/test.profdata"',
            'LLVM_PROFILE_FILE="$raw" "$bin"',
            '"$profdata" merge -o "$merged" "$raw"',
            '"$cov" report "$bin" -instr-profile="$merged" -show-branch-summary -show-mcdc-summary > "$report"',
            '"$cov" show "$bin" -instr-profile="$merged" -show-branches=count -show-mcdc > "$detail"',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args(
            ["/bin/sh", script, binary, ctx.attrs._profdata[RunInfo], ctx.attrs._cov[RunInfo], report.as_output(), detail.as_output()],
        ),
        category = "cov_report",
    )
    return [DefaultInfo(default_output = report, other_outputs = [detail])]

cov_report = rule(
    impl = _cov_report_impl,
    attrs = {
        "test": attrs.dep(),
        "_cov": attrs.exec_dep(default = "toolchains//:llvm-cov", providers = [RunInfo]),
        "_profdata": attrs.exec_dep(default = "toolchains//:llvm-profdata", providers = [RunInfo]),
    },
)
