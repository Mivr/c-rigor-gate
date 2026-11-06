"""Shared glue for gate subcommands: exit codes, result output, console summary."""

from rigor_lib import jsonio

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def print_summary(result):
    print("%s: %s (%d findings)" % (result.gate, result.status, len(result.findings)))
    for item in result.sorted_findings():
        print("  " + jsonio.canonical_dumps(item).decode("ascii").rstrip("\n"))


def gate_handler(run):
    """Wrap a gate's `run(args) -> GateResult` into a handler returning the exit code."""
    def handler(args):
        result = run(args)
        if args.out:
            jsonio.write_atomic(args.out, result.to_json_bytes())
        print_summary(result)
        return EXIT_PASS if result.status == "PASS" else EXIT_FAIL
    return handler
