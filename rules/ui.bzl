"""`c_ui_probe` (U03, P004 4.2, docs/ui-model.md): the probe binary of a product's UI model, and
`c_ui_probe_session` (U05c): a test that runs that probe on a checked-in session and compares its transcript.

The probe is the gate's `main` (`gate//ui/model:probe`, protocol `ui-probe/1`) linked with the product's model adapter,
a `c_library` that implements `ui/model/model.h`. The binary is a `c_binary` (the sealed C17 flags, the facts of every
mode), so it is built and graded like any product binary; there is no flag argument of any kind.

Confinement of the `uim_*` symbols is the symbols gate's, not this macro's (docs/ui-model.md, "Confinement"): the policy
denies every `uim_*` name globally and exempts the model adapter and nothing else.
"""

load("@gate//rules:c.bzl", "c_binary")
load("@gate//rules:ctest.bzl", "sanitizer_env_lines")

_PROBE = "gate//ui/model:probe"

# The modes a probe session runs in: the two the grade uses (docs/ui-model.md).
_SESSION_MODES = select({
    "toolchains//:release": [],
    "toolchains//:san": [],
    "DEFAULT": ["toolchains//:never"],
})

# What only a `c_ui_probe` gives: its probe binary. A session runs nothing else (no product script, no other binary).
UiProbeInfo = provider(fields = ["binary"])

def _label(macro, attr, value):
    if type(value) != "string" or ":" not in value or value.startswith("@"):
        fail("{}: `{}` must be a target label string, got {!r}".format(macro, attr, value))

def _probe_mark_impl(ctx: AnalysisContext) -> list[Provider]:
    binary = ctx.attrs.binary[DefaultInfo].default_outputs[0]
    return [DefaultInfo(default_output = binary), UiProbeInfo(binary = binary)]

_probe_mark = rule(
    impl = _probe_mark_impl,
    attrs = {"binary": attrs.dep()},
)

def c_ui_probe(name, model):
    """A probe binary `name` from `model`, a `c_library` that implements `gate//ui/model:model` (`ui/model/model.h`).

    There is no `deps`: the adapter library carries its own dependencies, and the gates judge them as they judge any
    library. The symbols gate exempts exactly one target from the `uim_` reservation, the `model` of a `c_ui_probe`.
    Built in the release and the san mode like every `c_binary`; the grade drives the san one, the release one proves
    the interface is the same in both (docs/ui-model.md). `<name>__ui_probe` marks the binary as a probe for
    `c_ui_probe_session` (nothing else may name it).
    """
    _label("c_ui_probe", "model", model)
    c_binary(name = name, srcs = [], deps = [model, _PROBE])
    _probe_mark(name = name + "__ui_probe", binary = ":" + name, target_compatible_with = _SESSION_MODES)

def _session_file(attr, value):
    if type(value) != "string":
        fail("c_ui_probe_session: `{}` must be one file of the package, got {}: {!r}".format(attr, type(value), value))
    parts = value.split("/")
    if value == "" or value.startswith("@") or ":" in value or "*" in value or "\\" in value or \
       "" in parts or "." in parts or ".." in parts:
        fail("c_ui_probe_session: `{}` must be one plain file of the package (no label, glob, `.`, `..` or absolute path), got {!r}".format(attr, value))

def _session_impl(ctx: AnalysisContext) -> list[Provider]:
    results = ctx.actions.declare_output("results.jsonl")
    report = ctx.actions.declare_output("report.txt")
    verdict = ctx.actions.declare_output("verdict")
    script = ctx.actions.write(
        "run.sh",
        [
            "set -u",
            'sym="$1"; shift',
            'sym="$(cd "$(dirname "$sym")" && pwd)/$(basename "$sym")"',
            # The sealed sanitizer options of a `c_test` (rules/ctest.bzl), with the reports on the probe's stderr.
        ] + sanitizer_env_lines(None) + [
            'exec /usr/bin/env python3 -I -B "$@"',
        ],
        is_executable = True,
    )
    ctx.actions.run(
        cmd_args([
            "/bin/sh",
            script,
            ctx.attrs._symbolizer[RunInfo],
            ctx.attrs._runner,
            "--probe",
            ctx.attrs.probe[UiProbeInfo].binary,
            "--session",
            ctx.attrs.session,
            "--expected",
            ctx.attrs.expected,
            "--id",
            ctx.attrs.test_id,
            "--label",
            str(ctx.label.raw_target()),
            "--out",
            results.as_output(),
            "--report",
            report.as_output(),
            "--verdict",
            verdict.as_output(),
        ]),
        category = "ui_probe_session",
    )
    check = ctx.actions.write(
        "check.sh",
        [
            'v="$(cat "$1")" || exit 1',
            'cat "$2"',
            '[ "$v" = pass ] || exit 1',
        ],
        is_executable = True,
    )
    return [
        DefaultInfo(
            default_output = results,
            other_outputs = [report, verdict],
            sub_targets = {
                "report": [DefaultInfo(default_output = report)],
                "verdict": [DefaultInfo(default_output = verdict)],
            },
        ),
        ExternalRunnerTestInfo(
            type = "custom",
            command = ["/bin/sh", check, verdict, report],
            labels = ["c_ui_probe_session"],
        ),
    ]

# The rule kind of every session target: `kind(ui_probe_session_run, //...)` lists them (a stable, public name).
ui_probe_session_run = rule(
    impl = _session_impl,
    attrs = {
        "expected": attrs.source(),
        "probe": attrs.dep(providers = [UiProbeInfo]),
        "session": attrs.source(),
        "test_id": attrs.string(),
        "_runner": attrs.source(default = "gate//ui/model:probe_session.py"),
        "_symbolizer": attrs.exec_dep(default = "toolchains//:llvm-symbolizer", providers = [RunInfo]),
    },
)

def c_ui_probe_session(name, probe, session, expected):
    """A test `name`: the probe of `probe` (`":<name>"` of a `c_ui_probe` of this package) run once with the checked-in
    command file `session` on stdin, in release and in san (each mode its own result).

    It passes only if the session's last line is `quit`, the probe exits 0, writes nothing on stderr and its stdout is
    byte-identical to the checked-in `expected`; the report names every failed check and the first differing line with
    its number. The run is a cacheable build action (`gate//ui/model:probe_session.py`, stdlib Python): the default
    output of `name` is its result in the JSON Lines of `ctest`, one test id `ui_probe_session/<package, `/` as `.`>:<name>`;
    `buck2 test` reads the verdict. A product supplies data files only (docs/ui-model.md, "`c_ui_probe_session`").

    ENFORCED BY `buck2 test` ONLY, NOT YET BY `rigor grade`: the grade's build gate collects only `ctest_results` targets
    (gate/rigor_lib/grade_build.py, `result_targets`). The follow-up: query `kind(ui_probe_session_run, //...)` there
    too and copy each default output into the results directory, so the tests gate sees the id
    `ui_probe_session/<pkg>:<name>` like any ctest id; and a selftest step in which a failing session fails a grade.
    """
    if type(probe) != "string" or not probe.startswith(":") or "/" in probe or "__" in probe or len(probe) < 2:
        fail("c_ui_probe_session {}: `probe` must be the label \":name\" of a c_ui_probe of this package, got {!r}".format(name, probe))
    _session_file("session", session)
    _session_file("expected", expected)
    if session == expected:
        fail("c_ui_probe_session {}: `session` and `expected` must be two files, got {!r} twice".format(name, session))
    package = native.package_name()
    ui_probe_session_run(
        name = name,
        probe = probe + "__ui_probe",
        session = session,
        expected = expected,
        test_id = "ui_probe_session/{}:{}".format(package.replace("/", "."), name),
        target_compatible_with = _SESSION_MODES,
    )
