"""Execution and target platforms: linux-x86_64, executed on the RE farm only."""

# Properties that select the farm's Linux x86_64 workers (same routing keys as the other
# repos on this farm). The worker image digest is part of every action digest, so a
# change of image can never reuse cached results from another image.
def re_properties(worker_image: str) -> dict[str, str]:
    props = {
        "OSFamily": "linux",
        "cpu_arch": "x86_64",
        "container-image": "",
        "sb-gate": "1",
        "cpu_count": "1",
    }
    if worker_image:
        props["sb.worker_image"] = worker_image
    return props

def _exec_platform_impl(ctx: AnalysisContext) -> list[Provider]:
    constraints = {}
    constraints.update(ctx.attrs.cpu_configuration[ConfigurationInfo].constraints)
    constraints.update(ctx.attrs.os_configuration[ConfigurationInfo].constraints)
    cfg = ConfigurationInfo(constraints = constraints, values = {})
    platform = ExecutionPlatformInfo(
        label = ctx.label.raw_target(),
        configuration = cfg,
        executor_config = CommandExecutorConfig(
            local_enabled = False,
            remote_enabled = True,
            remote_execution_properties = re_properties(ctx.attrs.worker_image),
            remote_execution_use_case = "buck2-default",
        ),
    )
    return [
        DefaultInfo(),
        platform,
        ExecutionPlatformRegistrationInfo(platforms = [platform]),
    ]

exec_platform = rule(
    impl = _exec_platform_impl,
    attrs = {
        "cpu_configuration": attrs.dep(providers = [ConfigurationInfo]),
        "os_configuration": attrs.dep(providers = [ConfigurationInfo]),
        "worker_image": attrs.string(default = ""),
    },
)

def _target_platform_impl(ctx: AnalysisContext) -> list[Provider]:
    constraints = {}
    constraints.update(ctx.attrs.cpu_configuration[ConfigurationInfo].constraints)
    constraints.update(ctx.attrs.os_configuration[ConfigurationInfo].constraints)
    constraints.update(ctx.attrs.mode[ConfigurationInfo].constraints)
    cfg = ConfigurationInfo(constraints = constraints, values = {})
    return [
        DefaultInfo(),
        PlatformInfo(label = str(ctx.label.raw_target()), configuration = cfg),
    ]

target_platform = rule(
    impl = _target_platform_impl,
    attrs = {
        "cpu_configuration": attrs.dep(providers = [ConfigurationInfo]),
        "os_configuration": attrs.dep(providers = [ConfigurationInfo]),
        "mode": attrs.dep(providers = [ConfigurationInfo]),
    },
)
