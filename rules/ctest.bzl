"""`<name>_results`: the JSON Lines a ctest binary produces, as a cacheable build artifact.

The test binary runs on RE with a fixed seed. The action succeeds whenever the binary ran
(exit 0: all passed, exit 1: some test failed) so the gate sees failures in the file, not as a
missing artifact. It fails when the binary could not run at all: exit status 2 (usage or
framework error), death by signal, or no results file.
"""

def sanitizer_env_lines(log_path = None):
    """Shell lines that export the hermetic symbolizer and the fatal sanitizer options.

    Expects `$sym` (absolute path of llvm-symbolizer). `log_path` is a shell expression, or None to
    leave reports on stderr. Shared by `<name>_results` and `fuzz_run`; never weaken these.
    """
    log = (":log_path=" + log_path) if log_path else ""
    return [
        "export ASAN_SYMBOLIZER_PATH=\"$sym\" LLVM_SYMBOLIZER_PATH=\"$sym\"",
        'common="symbolize=1:fast_unwind_on_malloc=0:strip_path_prefix=$(pwd)/' + log + '"',
        'export ASAN_OPTIONS="$common:halt_on_error=1:abort_on_error=0:detect_leaks=1:handle_abort=1:handle_sigill=1:handle_sigbus=1:handle_sigfpe=1"',
        'export UBSAN_OPTIONS="$common:halt_on_error=1:abort_on_error=0:print_stacktrace=1"',
        'export LSAN_OPTIONS="$common"',
    ]

# Extra sealed options of the msan mode (`ctest_results` only; the san and release scripts are unchanged). `ctest`
# forks one process per test and the sanitizer log is read per pid, so `log_path` (in `$common`) is all the fork
# needs. `halt_on_error=1`: the first report ends the test process (exit 77), which `ctest` reports as a failure
# together with the log. `external_symbolizer_path` is the hermetic llvm-symbolizer (MSan does not read
# ASAN_SYMBOLIZER_PATH).
MSAN_ENV_LINES = [
    'export MSAN_OPTIONS="$common:external_symbolizer_path=$sym:halt_on_error=1:exitcode=77:abort_on_error=0:handle_abort=1:handle_sigill=1:handle_sigbus=1:handle_sigfpe=1:print_stats=0"',
]

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
        ] + sanitizer_env_lines('"$log"') + ctx.attrs.env_lines + [
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
        "env_lines": attrs.list(attrs.string(), default = []),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)

# ---------------------------------------------------------------------------------------------
# c_fuzz: the fuzz run is a build action with declared outputs; the test only reads its verdict.
# ---------------------------------------------------------------------------------------------

# Lines of the raw libFuzzer/sanitizer log that go into the report; everything else (progress
# lines with timings and RSS, module addresses, seeds of the mutation engine) varies or is noise.
_KEEP = "^==[0-9]+==ERROR|^ERROR: libFuzzer|^SUMMARY:|runtime error|^ +#[0-9]+ |^(READ|WRITE) of size|is located|^(allocated|freed) by|^0x[0-9a-f][0-9a-f],|^Base64:"

# Runtime-internal frames (libFuzzer, the sanitizer runtime, libc start-up) are noise for whoever fixes the product.
_DROP = "llvm-project/|/lib/x86_64-linux-gnu/|in __libc_start_main|in _start "

def _fuzz_run_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.binary[DefaultInfo].default_outputs[0]
    report = ctx.actions.declare_output("report.txt")
    crash = ctx.actions.declare_output("crash")
    verdict = ctx.actions.declare_output("verdict")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; report="$2"; crash="$3"; verdict="$4"; sym="$5"',
            'here="$(cd "$(dirname "$report")" && pwd)"',
            'sym="$(cd "$(dirname "$sym")" && pwd)/$(basename "$sym")"',
            'cwd="$(pwd)"; work="$here/work"; raw="$work/raw.txt"',
            'rm -rf "$work"; mkdir -p "$work"',
        ] + sanitizer_env_lines() + [
            # Sanitizer reports stay on stderr (no log_path) and are captured with libFuzzer's own log.
            "rc=0",
            '"$bin" -seed=1 -runs=200000 -artifact_prefix="$work/" >"$work/stdout.txt" 2>"$raw" || rc=$?',
            # The verdict is written here, after the target exited: nothing the target or its log says
            # can change it. A clean run needs exit 0 and libFuzzer's own completion line.
            'v="fail rc=$rc"',
            'if [ "$rc" -eq 0 ] && grep -q "^Done 200000 runs in " "$raw"; then v=pass; fi',
            'echo "$v" > "$verdict"',
            # The reproducer: libFuzzer's crash/timeout/oom/leak file (names are content hashes). A passing
            # run has an empty one, so a pass never varies. Slow-unit files are timing dependent: ignored.
            ': > "$crash"; rname=""',
            'if [ "$v" != pass ]; then',
            '  for f in "$work"/crash-* "$work"/timeout-* "$work"/oom-* "$work"/leak-*; do',
            '    [ -f "$f" ] && { cp "$f" "$crash"; rname="$(basename "$f")"; break; }',
            "  done",
            "fi",
            "{",
            '  echo "fuzz: -seed=1 -runs=200000 verdict: $v"',
            '  [ -n "$rname" ] && echo "reproducer: $rname (the crash output; feed it to the fuzz binary to replay)"',
            "  grep -E '" + _KEEP + "' \"$raw\" | grep -Ev '" + _DROP + "' | sed -E \"s|$cwd/||g; s|$here/||g; s/^==[0-9]+==/==PID==/; s/0x[0-9a-fA-F]{6,}/0xADDR/g\"",
            '} > "$report"',
            'rm -rf "$work"',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args(["/bin/sh", script, binary, report.as_output(), crash.as_output(), verdict.as_output(), ctx.attrs._symbolizer[RunInfo]]),
        category = "fuzz_run",
    )
    check = ctx.actions.write(
        "check.sh",
        [
            'v="$(cat "$1")" || exit 1',
            'cat "$2"',
            '[ "$v" = pass ] || { echo "fuzz: FAILED ($v)"; exit 1; }',
            'echo "fuzz: passed"',
        ],
        is_executable = True,
    )
    return [
        DefaultInfo(
            default_output = report,
            other_outputs = [crash, verdict],
            sub_targets = {
                "crash": [DefaultInfo(default_output = crash)],
                "report": [DefaultInfo(default_output = report)],
            },
        ),
        ExternalRunnerTestInfo(
            type = "custom",
            command = ["/bin/sh", check, verdict, report],
            labels = ["c_fuzz"],
        ),
    ]

fuzz_run = rule(
    impl = _fuzz_run_impl,
    attrs = {
        "binary": attrs.dep(),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)
