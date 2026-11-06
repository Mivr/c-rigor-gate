"""`<name>_results`: the JSON Lines a ctest binary produces, as a cacheable build artifact.

The test binary runs on RE with a fixed seed. The action succeeds whenever the binary ran
(exit 0: all passed, exit 1: some test failed) so the gate sees failures in the file, not as a
missing artifact. It fails when the binary could not run at all: exit status 2 (usage or
framework error), death by signal, or no results file.
"""

def _ctest_results_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.test[DefaultInfo].default_outputs[0]
    results = ctx.actions.declare_output("results.jsonl")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'bin="$1"; out="$2"',
            "rc=0",
            '"$bin" --seed 1 --out "$out" || rc=$?',
            'if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then',
            '  echo "ctest: test binary could not run (status $rc)" >&2; exit 1',
            "fi",
            '[ -s "$out" ] || { echo "ctest: no results written" >&2; exit 1; }',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args(["/bin/sh", script, binary, results.as_output()]),
        category = "ctest_results",
    )
    return [DefaultInfo(default_output = results)]

ctest_results = rule(
    impl = _ctest_results_impl,
    attrs = {
        "test": attrs.dep(),
    },
)
