"""`<name>_perf`: the cost counts (`perf.jsonl`) of a perf binary, as a cacheable build artifact (docs/perf.md).

The binary is run on RE with the sizes and the seed taken from rule attributes. The action
succeeds whenever the harness ran and wrote its records (statuses and an unavailable counter are
records, not action failures); it fails only when the harness could not run at all.
"""

# The libc functions whose `len` is summed. Must match the __wrap_ definitions in ctest/perf.c.
PERF_WRAPS = ["memcpy", "memmove", "memset", "memcmp", "strlen", "strnlen"]

def _perf_results_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.binary[DefaultInfo].default_outputs[0]
    out = ctx.actions.declare_output("perf.jsonl")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; out="$2"; name="$3"; seed="$4"; sizes="$5"',
            "rc=0",
            '"$bin" --name "$name" --seed "$seed" --sizes "$sizes" --out "$out" || rc=$?',
            'if [ "$rc" -ne 0 ]; then echo "perf: harness could not run (status $rc)" >&2; exit 1; fi',
            '[ -s "$out" ] || { echo "perf: no records written" >&2; exit 1; }',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args([
            "/bin/sh",
            script,
            binary,
            out.as_output(),
            ctx.attrs.perf_name,
            str(ctx.attrs.seed),
            ",".join([str(n) for n in ctx.attrs.sizes]),
        ]),
        category = "perf_run",
    )
    return [DefaultInfo(default_output = out)]

perf_results = rule(
    impl = _perf_results_impl,
    attrs = {
        "binary": attrs.dep(),
        "perf_name": attrs.string(),
        "seed": attrs.int(),
        "sizes": attrs.list(attrs.int()),
    },
)
