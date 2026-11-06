"""Fetch an archive by sha256 and extract only the listed members, remotely.

`http_archive` extracts the whole archive; the LLVM release is 2 GB compressed and 7 GB
unpacked. Every action that consumed it would be tied to that tree. This rule downloads
the archive (checked against `sha256`, so a changed upstream file fails the build) and
runs `tar` on the RE farm to unpack only `members`, so the artifact is the small subset
the toolchain actually uses. A pattern that matches nothing fails the build.
"""

def _fetched_tree_impl(ctx: AnalysisContext) -> list[Provider]:
    archive = ctx.actions.declare_output("archive.tar.xz")
    ctx.actions.download_file(
        archive.as_output(),
        ctx.attrs.url,
        sha256 = ctx.attrs.sha256,
        size_bytes = ctx.attrs.size_bytes,
    )

    members, _ = ctx.actions.write("members.txt", ctx.attrs.members, allow_args = True)
    out = ctx.actions.declare_output("tree", dir = True)
    strip = ["--strip-components=" + str(ctx.attrs.strip_components)] if ctx.attrs.strip_components else []
    script = cmd_args(
        "set -eu",
        cmd_args(out.as_output(), format = "mkdir -p {}"),
        cmd_args(
            ["tar", "-xJf", archive, "-C", out.as_output(), "--wildcards", "--no-wildcards-match-slash", "-T", members] + strip,
            delimiter = " ",
        ),
        delimiter = "\n",
    )
    ctx.actions.run(
        cmd_args(["/bin/sh", "-c", script], hidden = [archive, members, out.as_output()]),
        category = "fetched_tree",
        identifier = ctx.label.name,
    )
    return [DefaultInfo(default_output = out)]

fetched_tree = rule(
    impl = _fetched_tree_impl,
    attrs = {
        "members": attrs.list(attrs.string()),
        "sha256": attrs.string(),
        "size_bytes": attrs.int(),
        "strip_components": attrs.int(default = 0),
        "url": attrs.string(),
    },
)
