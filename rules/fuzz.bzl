"""`c_fuzz` runs (T126, P003 W6): the fuzz run is a build action with declared outputs; the test only reads its verdict.

The action does, in this order: (1) *replay* of every corpus file of the product, one process per file, in the order of
their sha256 (a crash here is a regression); (2) the *budget*: `-seed=1 -runs=N` seeded with the corpus. N is a number of
runs, never a time, so the action stays deterministic and cacheable. Outputs: `report`, `crash` (the reproducer),
`verdict`, `stats.json` (`rigor fuzz` reads it) and `replayed` (the sha256 of every corpus file that was replayed).
The sanitizer settings are `sanitizer_env_lines` of rules/ctest.bzl, never weakened. See docs/fuzz.md.
"""

load("@gate//rules:ctest.bzl", "sanitizer_env_lines")

# The budget of a target: sealed default and sealed maximum, in runs. `gate/rigor_lib/fuzz_gate.py` holds the same
# default (what the judge demands when the policy sets no `fuzz_runs`) and the same maximum; a unit test compares them.
FUZZ_DEFAULT_RUNS = 200000
FUZZ_MAX_RUNS = 2000000

def fuzz_runs(macro, runs):
    """The validated budget of a `c_fuzz`: `None` is the default; anything above the maximum is a loading error."""
    if runs == None:
        return FUZZ_DEFAULT_RUNS
    if type(runs) != "int" or runs < 1 or runs > FUZZ_MAX_RUNS:
        fail("{}: `runs` must be an integer in [1, {}], got {!r}".format(macro, FUZZ_MAX_RUNS, runs))
    return runs

def fuzz_corpus(macro, corpus):
    """The validated corpus: a list of plain relative file paths of the product (a `glob`), never a label."""
    if type(corpus) != "list":
        fail("{}: `corpus` must be a list of files, got {}".format(macro, type(corpus)))
    for item in corpus:
        if type(item) != "string" or not item or item.startswith(("/", "@", ":")) or ":" in item or ".." in item.split("/"):
            fail("{}: corpus entry {!r} must be a plain relative file path of this package".format(macro, item))
    return corpus

# Lines of the raw libFuzzer/sanitizer log that go into the report; everything else (progress
# lines with timings and RSS, module addresses, seeds of the mutation engine) varies or is noise.
_KEEP = "^==[0-9]+==ERROR|^ERROR: libFuzzer|^SUMMARY:|runtime error|^ +#[0-9]+ |^(READ|WRITE) of size|is located|^(allocated|freed) by|^0x[0-9a-f][0-9a-f],|^Base64:"

# Runtime-internal frames (libFuzzer, the sanitizer runtime, libc start-up) are noise for whoever fixes the product.
_DROP = "llvm-project/|/lib/x86_64-linux-gnu/|in __libc_start_main|in _start "

def _run_script(ctx: AnalysisContext):
    return ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; report="$2"; crash="$3"; verdict="$4"; stats="$5"; replayed_out="$6"; sym="$7"; runs="$8"; shift 8',
            'here="$(cd "$(dirname "$report")" && pwd)"',
            'sym="$(cd "$(dirname "$sym")" && pwd)/$(basename "$sym")"',
            'cwd="$(pwd)"; work="$here/work"; raw="$work/raw.txt"',
            'rm -rf "$work"; mkdir -p "$work"',
        ] + sanitizer_env_lines() + [
            # The corpus, sorted by content hash: the order does not depend on file names or on how the product
            # laid them out. The manifest has one `<sha256> <path>` line per file.
            ': > "$work/unsorted"; : > "$raw"; : > "$work/stdout.txt"',
            'for f in "$@"; do',
            '  h="$(sha256sum "$f")" || exit 1',
            '  printf \'%s %s\\n\' "${h%% *}" "$f" >> "$work/unsorted"',
            "done",
            'LC_ALL=C sort "$work/unsorted" > "$work/manifest" || exit 1',
            'ncorp="$(wc -l < "$work/manifest")"; ncorp=$((ncorp + 0))',
            # 1. replay: every corpus file once (-runs=0), one process per file; the first crash stops the run.
            ': > "$replayed_out"; rc=0; replayed=0; phase=budget; failed=""',
            'while IFS= read -r line; do',
            '  [ -n "$line" ] || continue',
            '  rrc=0',
            '  "$bin" -runs=0 -artifact_prefix="$work/" "${line#* }" >>"$work/stdout.txt" 2>>"$raw" || rrc=$?',
            '  if [ "$rrc" -ne 0 ]; then rc="$rrc"; phase=replay; failed="$line"; break; fi',
            '  replayed=$((replayed + 1)); echo "${line%% *}" >> "$replayed_out"',
            'done < "$work/manifest"',
            # 2. budget: -seed=1 -runs=N seeded with the corpus.
            # libFuzzer fuzzes only when it is given a corpus *directory* (files alone are executed once, nothing is
            # fuzzed), and it writes new units into it: a private copy in the scratch directory, thrown away.
            "set --",
            'if [ "$ncorp" -gt 0 ]; then',
            '  mkdir -p "$work/seed"',
            '  while IFS= read -r line; do [ -n "$line" ] && cp "${line#* }" "$work/seed/${line%% *}"; done < "$work/manifest"',
            '  set -- "$work/seed"',
            "fi",
            'if [ "$phase" = budget ]; then',
            '  "$bin" -seed=1 -runs="$runs" -print_final_stats=1 -artifact_prefix="$work/" "$@" >>"$work/stdout.txt" 2>>"$raw" || rc=$?',
            "fi",
            # The verdict is written here, after the target exited: nothing the target or its log says
            # can change it. A clean run needs exit 0 and libFuzzer's own completion line.
            'v="fail rc=$rc"',
            'if [ "$rc" -eq 0 ] && grep -q "^Done $runs runs in " "$raw"; then v=pass; fi',
            'echo "$v" > "$verdict"',
            # The reproducer: libFuzzer's crash/timeout/oom/leak file (names are content hashes). A passing
            # run has an empty one, so a pass never varies. Slow-unit files are timing dependent: ignored.
            ': > "$crash"; rname=""; rsha=""',
            'if [ "$v" != pass ]; then',
            '  for f in "$work"/crash-* "$work"/timeout-* "$work"/oom-* "$work"/leak-*; do',
            '    [ -f "$f" ] && { cp "$f" "$crash"; rname="$(basename "$f")"; break; }',
            "  done",
            # libFuzzer writes no artifact for a corpus file that crashes the replay: the file is the reproducer.
            '  [ "$phase" = replay ] && [ -z "$rname" ] && { cp "${failed#* }" "$crash"; rname="corpus-${failed%% *}"; }',
            '  [ -n "$rname" ] && { h="$(sha256sum "$crash")" || exit 1; rsha="${h%% *}"; }',
            "fi",
            # runs_done: the executed units of the budget run (a crash prints them too); 0 for a crash in the replay.
            'done_runs=0',
            'if [ "$phase" = budget ]; then',
            "  n=\"$(sed -n 's/^stat::number_of_executed_units: *//p' \"$raw\" | tail -n 1)\"",
            '  [ -n "$n" ] && done_runs=$((n + 0))',
            "fi",
            'printf \'{"corpus_files":%s,"phase":"%s","replayed":%s,"reproducer_sha256":"%s","runs_done":%s}\\n\' "$ncorp" "$phase" "$replayed" "$rsha" "$done_runs" > "$stats"',
            "{",
            '  echo "fuzz: -seed=1 -runs=$runs verdict: $v"',
            '  [ "$ncorp" -gt 0 ] && echo "replay: $replayed of $ncorp corpus files"',
            '  [ -n "$rname" ] && echo "reproducer: $rname (the crash output; feed it to the fuzz binary to replay)"',
            "  grep -E '" + _KEEP + "' \"$raw\" | grep -Ev '" + _DROP + "' | sed -E \"s|$cwd/||g; s|$here/||g; s/^==[0-9]+==/==PID==/; s/0x[0-9a-fA-F]{6,}/0xADDR/g\"",
            '} > "$report"',
            'rm -rf "$work"',
        ],
        is_executable = True,
    )

def _fuzz_run_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.binary[DefaultInfo].default_outputs[0]
    report = ctx.actions.declare_output("report.txt")
    crash = ctx.actions.declare_output("crash")
    verdict = ctx.actions.declare_output("verdict")
    stats = ctx.actions.declare_output("stats.json")
    replayed = ctx.actions.declare_output("replayed.txt")
    ctx.actions.run(
        cmd_args(
            ["/bin/sh", _run_script(ctx), binary, report.as_output(), crash.as_output(), verdict.as_output(), stats.as_output(), replayed.as_output(), ctx.attrs._symbolizer[RunInfo], str(ctx.attrs.runs)],
            ctx.attrs.corpus,
        ),
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
            other_outputs = [crash, verdict, stats, replayed],
            sub_targets = {
                "crash": [DefaultInfo(default_output = crash)],
                "replayed": [DefaultInfo(default_output = replayed)],
                "report": [DefaultInfo(default_output = report)],
                "stats": [DefaultInfo(default_output = stats)],
                "verdict": [DefaultInfo(default_output = verdict)],
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
        "corpus": attrs.list(attrs.source(), default = []),
        "runs": attrs.int(default = FUZZ_DEFAULT_RUNS),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)
