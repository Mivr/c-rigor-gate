"""`c_sim` runs (T2G1, P330 §1): the simulation run is a build action with declared outputs; the test only reads its verdict.

`sim_run` runs one shard of seeds of the world binary (the gate's runner linked with the product's world): per seed, a
forked child runs the seeded day twice on fresh worlds; every way of not finishing is a rule in `stats.json`, never a skip.
`sim_merge` joins the shards into the one verdict of the target. See docs/sim.md.

Seeds are derived from `salt`, the hash of the world's source files (the same in every mode, so release and san run
the same seeds) and the seed index; the salt comes from `-c rigor.sim_salt=HEX` (the grader's hidden one, T2G2) and is
empty otherwise. The sanitizer settings are `sanitizer_env_lines` of rules/ctest.bzl, never weakened.
"""

load("@gate//rules:ctest.bzl", "sanitizer_env_lines")

# Sealed defaults and maxima; `gate/rigor_lib/sim_*` and docs/sim.md hold the same numbers [P: T2G9 sets them by measurement].
SIM_DEFAULT_SEEDS = 200
SIM_MAX_SEEDS = 4096
SIM_DEFAULT_RUN_MS = 3600000
SIM_MAX_RUN_MS = 86400000
SIM_MAX_SHARDS = 16
SIM_STEP_LIMIT = 50000000
SIM_REAL_LIMIT_S = 120

def _int_in(macro, name, value, default, low, high):
    if value == None:
        return default
    if type(value) != "int" or value < low or value > high:
        fail("{}: `{}` must be an integer in [{}, {}], got {!r}".format(macro, name, low, high, value))
    return value

def sim_params(macro, seeds, run_ms, shards):
    """The validated (seeds, run_ms, shards) of a `c_sim`; anything out of range is a loading error."""
    seeds = _int_in(macro, "seeds", seeds, SIM_DEFAULT_SEEDS, 1, SIM_MAX_SEEDS)
    run_ms = _int_in(macro, "run_ms", run_ms, SIM_DEFAULT_RUN_MS, 250, SIM_MAX_RUN_MS)
    shards = _int_in(macro, "shards", shards, 1, 1, min(SIM_MAX_SHARDS, seeds))
    return seeds, run_ms, shards

def sim_salt():
    """The salt of the seed derivation: lowercase hex from `-c rigor.sim_salt=`, empty by default."""
    salt = read_config("rigor", "sim_salt", "")
    if len(salt) % 2 != 0 or len(salt) > 128 or any([c not in "0123456789abcdef" for c in salt.elems()]):
        fail("rigor.sim_salt must be lowercase hex of at most 64 bytes, got {!r}".format(salt))
    return salt

_KEEP = "^==[0-9]+==ERROR|^SUMMARY:|runtime error|^ +#[0-9]+ |^(READ|WRITE) of size|is located|^(allocated|freed) by|^seed |^sim:"
_DROP = "llvm-project/|/lib/x86_64-linux-gnu/|in __libc_start_main|in _start "

def _run_script(ctx: AnalysisContext):
    return ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; stats="$2"; hashes="$3"; verdict="$4"; report="$5"; sym="$6"; first="$7"; count="$8"; run_ms="$9"; steps="${10}"; real="${11}"; salt="${12}"; shift 12',
            'here="$(cd "$(dirname "$report")" && pwd)"',
            'sym="$(cd "$(dirname "$sym")" && pwd)/$(basename "$sym")"',
            'cwd="$(pwd)"; work="$here/work"',
            'rm -rf "$work"; mkdir -p "$work"',
        ] + sanitizer_env_lines() + [
            # The hash of the world's sources: the content hashes of its files, sorted. The same in every mode.
            ': > "$work/srcs"',
            'for f in "$@"; do h="$(sha256sum < "$f")" || exit 1; echo "${h%% *}" >> "$work/srcs"; done',
            'w="$(LC_ALL=C sort "$work/srcs" | sha256sum)" || exit 1; w="${w%% *}"',
            "rc=0",
            '"$bin" --world-sha256 "$w" --salt "$salt" --first "$first" --count "$count" --run-ms "$run_ms" --step-limit "$steps" --real-limit-s "$real" --stats "$stats" --hashes "$hashes" --verdict "$verdict" > "$work/stdout.txt" 2> "$work/stderr.txt" || rc=$?',
            # The runner exits 0 whenever it finished, also for a failing verdict (the verdict file says so); anything else is no verdict.
            'if [ "$rc" -ne 0 ]; then echo "sim: runner could not run (status $rc)" >&2; cat "$work/stderr.txt" >&2; exit 1; fi',
            'for f in "$stats" "$hashes" "$verdict"; do [ -f "$f" ] || { echo "sim: missing output $f" >&2; exit 1; }; done',
            "{",
            '  cat "$work/stdout.txt"',
            "  grep -E '" + _KEEP + "' \"$work/stderr.txt\" | grep -Ev '" + _DROP + "' | sed -E \"s|$cwd/||g; s|$here/||g; s/^==[0-9]+==/==PID==/; s/0x[0-9a-fA-F]{6,}/0xADDR/g\"",
            '} > "$report"',
            'rm -rf "$work"',
        ],
        is_executable = True,
    )

def _sim_run_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.binary[DefaultInfo].default_outputs[0]
    stats = ctx.actions.declare_output("stats.json")
    hashes = ctx.actions.declare_output("hashes.txt")
    verdict = ctx.actions.declare_output("verdict")
    report = ctx.actions.declare_output("report.txt")
    ctx.actions.run(
        cmd_args(
            [
                "/bin/sh",
                _run_script(ctx),
                binary,
                stats.as_output(),
                hashes.as_output(),
                verdict.as_output(),
                report.as_output(),
                ctx.attrs._symbolizer[RunInfo],
                str(ctx.attrs.first),
                str(ctx.attrs.count),
                str(ctx.attrs.run_ms),
                str(SIM_STEP_LIMIT),
                str(SIM_REAL_LIMIT_S),
                ctx.attrs.salt if ctx.attrs.salt else "",
            ],
            ctx.attrs.world_srcs,
        ),
        category = "sim_run",
    )
    return [DefaultInfo(
        default_output = report,
        other_outputs = [stats, hashes, verdict],
        sub_targets = {
            "hashes": [DefaultInfo(default_output = hashes)],
            "report": [DefaultInfo(default_output = report)],
            "stats": [DefaultInfo(default_output = stats)],
            "verdict": [DefaultInfo(default_output = verdict)],
        },
    )]

sim_run = rule(
    impl = _sim_run_impl,
    attrs = {
        "binary": attrs.dep(),
        "count": attrs.int(),
        "first": attrs.int(),
        "run_ms": attrs.int(),
        "salt": attrs.string(default = ""),
        "world_srcs": attrs.list(attrs.source(), default = []),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)

def _sim_merge_impl(ctx: AnalysisContext) -> list[Provider]:
    stats = ctx.actions.declare_output("stats.json")
    hashes = ctx.actions.declare_output("hashes.txt")
    verdict = ctx.actions.declare_output("verdict")
    report = ctx.actions.declare_output("report.txt")
    cmd = cmd_args(
        "/usr/bin/env",
        "python3",
        "-I",
        "-B",
        ctx.attrs._merge,
        "--expect",
        str(ctx.attrs.seeds),
        "--out-stats",
        stats.as_output(),
        "--out-hashes",
        hashes.as_output(),
        "--out-verdict",
        verdict.as_output(),
    )
    reports = []
    for shard in ctx.attrs.shards:
        subs = shard[DefaultInfo].sub_targets
        cmd.add(
            "--shard",
            subs["stats"][DefaultInfo].default_outputs[0],
            subs["hashes"][DefaultInfo].default_outputs[0],
            subs["verdict"][DefaultInfo].default_outputs[0],
        )
        reports.append(subs["report"][DefaultInfo].default_outputs[0])
    ctx.actions.run(cmd, category = "sim_merge")
    cat = ctx.actions.write(
        "report.sh",
        ['out="$1"; shift', 'cat "$@" > "$out"'],
        is_executable = True,
    )
    ctx.actions.run(cmd_args(["/bin/sh", cat, report.as_output()] + reports), category = "sim_report")
    check = ctx.actions.write(
        "check.sh",
        [
            'v="$(cat "$1")" || exit 1',
            'cat "$2"',
            'case "$v" in pass) echo "sim: passed";; *) echo "sim: FAILED ($v)"; exit 1;; esac',
        ],
        is_executable = True,
    )
    return [
        DefaultInfo(
            default_output = report,
            other_outputs = [stats, hashes, verdict],
            sub_targets = {
                "hashes": [DefaultInfo(default_output = hashes)],
                "report": [DefaultInfo(default_output = report)],
                "stats": [DefaultInfo(default_output = stats)],
                "verdict": [DefaultInfo(default_output = verdict)],
            },
        ),
        ExternalRunnerTestInfo(
            type = "custom",
            command = ["/bin/sh", check, verdict, report],
            labels = ["c_sim"],
        ),
    ]

sim_merge = rule(
    impl = _sim_merge_impl,
    attrs = {
        "seeds": attrs.int(),
        "shards": attrs.list(attrs.dep()),
        "_merge": attrs.source(default = "gate//gate/rigor_lib:sim_merge.py"),
    },
)
