"""Clone the product, and assemble the grading tree from gate files plus allowed product files.

Files are read as git blobs (`ls-tree` + `cat-file`), never from a working directory, so
`.gitattributes` (export-ignore, export-subst, filters) and symlinks cannot change what is copied.
"""

import os
import subprocess
from dataclasses import dataclass

from rigor_lib import gitrun, jsonio, paths
from rigor_lib.errors import InternalError

CLONE_TIMEOUT_SECONDS = 600
_FILE_MODES = {"100644": 0o644, "100755": 0o755}
# Gate files that must not enter tree/gate: it is a Buck2 cell, not the project root.
_GATE_SKIPPED = (".buckconfig", ".buckroot")
# Sections copied verbatim from the gate's own .buckconfig, so RE settings stay in one place.
_COPIED_SECTIONS = ("buck2_re_client", "http")

_BUCKCONFIG_HEAD = """\
[cells]
  root = .
  gate = gate
  toolchains = gate/toolchains
  prelude = prelude
  none = none

[cell_aliases]
  config = prelude
  ovr_config = prelude
  fbcode = none
  fbsource = none
  fbcode_macros = none
  buck = none

[external_cells]
  prelude = bundled

[project]
  ignore = .git, buck-out, cache

[build]
  execution_platforms = toolchains//:platforms

"""
_BUCKCONFIG_TAIL = """\
[parser]
  target_platform_detector_spec = target:root//...->toolchains//:linux_release
"""


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    kind: str
    blob: str
    path: bytes


def clone(source, dest):
    """`git clone --no-local --no-hardlinks` into `dest` with the hardened git environment."""
    if not os.path.isdir(source):
        raise InternalError("product repo is not a local directory: %s" % source)
    command = ["git", "--literal-pathspecs", "-c", "core.fsmonitor=false",
               "-c", "core.hooksPath=" + os.devnull, "-c", "protocol.allow=never",
               "-c", "protocol.file.allow=always", "clone", "--no-local", "--no-hardlinks",
               "--no-checkout", "--quiet", "--", source, dest]
    try:
        done = subprocess.run(command, env=gitrun.git_environment(), capture_output=True,
                              timeout=CLONE_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InternalError("cannot run git clone: %s" % exc) from exc
    if done.returncode != 0:
        raise InternalError("git clone failed: %s" % done.stderr.decode("utf-8", "replace").strip())


def checkout_detached(repo, head_sha):
    gitrun.run_git(repo, ["checkout", "--quiet", "--detach", "--force", head_sha])


def list_tree(repo, sha):
    """Every entry of the commit's tree (files, symlinks, gitlinks)."""
    raw = gitrun.run_git(repo, ["ls-tree", "-r", "-z", "--full-tree", sha])
    entries = []
    for item in raw.split(b"\0"):
        if item == b"":
            continue
        meta, separator, path = item.partition(b"\t")
        fields = meta.split(b" ")
        if separator == b"" or len(fields) != 3:
            raise InternalError("odd ls-tree entry")
        entries.append(TreeEntry(fields[0].decode("ascii"), fields[1].decode("ascii"),
                                 fields[2].decode("ascii"), path))
    return entries


def read_blob(repo, entry):
    return gitrun.run_git(repo, ["cat-file", "blob", entry.blob])


def write_file(root, rel_path, data, mode):
    """Create `root/rel_path` (it must not exist) and return the sha256 of its content."""
    reason = paths.unsafe_path_reason(rel_path)
    if reason is not None:
        raise InternalError("refusing to write %r: %s" % (rel_path, reason))
    target = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "xb") as handle:
        handle.write(data)
    os.chmod(target, mode)
    return jsonio.sha256_hex(data)


def write_symlink(root, rel_path, target):
    path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.symlink(target, path)
    return jsonio.sha256_hex(target)


def copy_gate(repo, sha, tree):
    """Put the gate commit's files under tree/gate. Returns ({tree path: sha256}, .buckconfig bytes)."""
    manifest = {}
    buckconfig = None
    for entry in list_tree(repo, sha):
        text = paths.match_text(entry.path)
        data = read_blob(repo, entry)
        if text == ".buckconfig":
            buckconfig = data
        if text in _GATE_SKIPPED:
            continue
        if entry.mode == "120000":  # gate-owned symlink (e.g. CLAUDE.md); never from a product
            manifest["gate/" + text] = write_symlink(os.path.join(tree, "gate"), text, data)
            continue
        if entry.mode not in _FILE_MODES:
            raise InternalError("gate commit holds an unsupported entry: %s" % text)
        manifest["gate/" + text] = write_file(os.path.join(tree, "gate"), text, data,
                                              _FILE_MODES[entry.mode])
    if buckconfig is None:
        raise InternalError("the gate commit has no .buckconfig")
    return manifest, buckconfig


def _section(text, name):
    lines = text.split("\n")
    header = "[%s]" % name
    for start, line in enumerate(lines):
        if line.strip() == header:
            end = start + 1
            while end < len(lines) and not lines[end].lstrip().startswith("["):
                end += 1
            return "\n".join(lines[start:end]).rstrip("\n") + "\n\n"
    raise InternalError("gate .buckconfig has no [%s] section" % name)


def generated_buckconfig(gate_buckconfig):
    """The only Buck2 configuration of a grading tree. Nothing of the product's goes in."""
    text = gate_buckconfig.decode("utf-8")
    copied = "".join(_section(text, name) for name in _COPIED_SECTIONS)
    return (_BUCKCONFIG_HEAD + copied + _BUCKCONFIG_TAIL).encode("utf-8")
