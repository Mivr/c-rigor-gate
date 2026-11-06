"""Verified reuse of the cached toolchain trees for `--uncached` builds (T030).

`--no-remote-cache` would make every Buck2 daemon re-run `tar -xJf` on the 1.6 GB LLVM archive (about
two minutes). The action cache is client-writable (backlog B4), so the tree may not simply be trusted
from it. Before every uncached `buck2 build` this module therefore runs two commands in the same daemon:

  1. `build toolchains//:{llvm,sysroot}_ref`, cache allowed, nothing materialised: the tree is taken from
     the action cache when present (the only time `tar` runs is when the cache truly lacks it);
  2. `build --no-remote-cache toolchains//:{llvm,sysroot}_verified`: an uncached worker action that hashes
     EVERY byte, mode bit, symlink and name of that very tree against the checked-in manifest
     (`toolchains/*.manifest`, gate files). Exit 0 only if tree and manifest are identical.

Buck2 keeps the tree of step 1 in the daemon, so the build that follows consumes the digest step 2
verified. Any difference (forged, extra, missing or altered member) makes step 2 fail, and the build is
reported as failed: there is never a silent re-fetch. Both steps cost seconds when the daemon is warm.
"""

CACHED_TARGETS = ["toolchains//:llvm_ref", "toolchains//:sysroot_ref"]
VERIFY_TARGETS = ["toolchains//:llvm_verified", "toolchains//:sysroot_verified"]
PLATFORM = "toolchains//:linux_release"
VERIFY_CATEGORY = "verify_tree"
_TAIL = 3000


def needs_verification(args):
    """True for a `buck2 build` that disables the remote cache."""
    return bool(args) and args[0] == "build" and "--no-remote-cache" in args


def _failure(step, code, err):
    return ("TOOLCHAIN VERIFICATION FAILED (%s, exit %d): the cached toolchain tree is not byte-identical "
            "to toolchains/*.manifest, or could not be checked. Not re-fetching.\n%s"
            % (step, code, err[-_TAIL:]))


def prepare(run, tree):
    """Run the two steps with `run(tree, args) -> (code, out, err)`. None if verified, else an error text."""
    base = ["build", "--target-platforms", PLATFORM, "--materializations", "none"]
    code, _, err = run(tree, base + CACHED_TARGETS)
    if code != 0:
        return _failure("fetch", code, err)
    code, _, err = run(tree, base + ["--no-remote-cache"] + VERIFY_TARGETS)
    if code != 0:
        return _failure("verify", code, err)
    code, out, err = run(tree, ["log", "what-ran"])
    if code != 0:
        return _failure("what-ran", code, err)
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and "(%s " % VERIFY_CATEGORY in fields[1] and fields[2] == "cache":
            return _failure("verify action was served from a cache", 0, line)
    return None
