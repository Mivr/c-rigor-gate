"""`<name>_results`: the JSON Lines a ctest binary produces, as a cacheable build artifact.

The test binary runs on RE with a fixed seed. The action succeeds whenever the binary ran
(exit 0: all passed, exit 1: some test failed) so the gate sees failures in the file, not as a
missing artifact. It fails when the binary could not run at all: exit status 2 (usage or
framework error), death by signal, or no results file.
"""

def _ctest_results_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.test[DefaultInfo].default_outputs[0]
    results = ctx.actions.declare_output("results.jsonl")
    san_report = ctx.actions.declare_output("san_report.txt")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; out="$2"; report="$3"; sym="$4"',
            # Absolute paths: a test may chdir before a sanitizer report is written or symbolized.
            'here="$(cd "$(dirname "$out")" && pwd)"',
            'sym="$(cd "$(dirname "$sym")" && pwd)/$(basename "$sym")"',
            'log="$here/sanlog"',
            # Hermetic symbolizer (a declared input), symbolized stack traces, and every failure fatal.
            # The sanitizer logs go to "$log.<pid>"; the binary reads them per test, strips pids and
            # addresses, and puts them in the report. Keep these options in sync with docs/ctest.md.
            "export ASAN_SYMBOLIZER_PATH=\"$sym\" LLVM_SYMBOLIZER_PATH=\"$sym\"",
            'common="symbolize=1:fast_unwind_on_malloc=0:strip_path_prefix=$(pwd)/:log_path=$log"',
            'export ASAN_OPTIONS="$common:halt_on_error=1:abort_on_error=0:detect_leaks=1:handle_abort=1:handle_sigill=1:handle_sigbus=1:handle_sigfpe=1"',
            'export UBSAN_OPTIONS="$common:halt_on_error=1:abort_on_error=0:print_stacktrace=1"',
            'export LSAN_OPTIONS="$common"',
            "rc=0",
            '"$bin" --seed 1 --out "$out" --san-log "$log" --san-report "$report" || rc=$?',
            'if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then',
            '  echo "ctest: test binary could not run (status $rc)" >&2; exit 1',
            "fi",
            '[ -s "$out" ] || { echo "ctest: no results written" >&2; exit 1; }',
            '[ -f "$report" ] || { echo "ctest: no sanitizer report written" >&2; exit 1; }',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args(["/bin/sh", script, binary, results.as_output(), san_report.as_output(), ctx.attrs._symbolizer[RunInfo]]),
        category = "ctest_results",
    )
    return [DefaultInfo(
        default_output = results,
        other_outputs = [san_report],
        sub_targets = {"san_report": [DefaultInfo(default_output = san_report)]},
    )]

ctest_results = rule(
    impl = _ctest_results_impl,
    attrs = {
        "test": attrs.dep(),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)
