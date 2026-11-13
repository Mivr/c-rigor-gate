"""Verified reuse of the cached toolchain trees for `--uncached` builds (T030, T073).

`--no-remote-cache` would make every Buck2 daemon re-run `tar -xJf` on the 1.6 GB LLVM archive (about
two minutes). The action cache is client-writable (backlog B4), so the tree may not simply be trusted
from it. Before uncached builds a daemon is therefore primed with two commands:

  1. `build toolchains//:{llvm,sysroot,ndk}_ref`, cache allowed, nothing materialised: the tree is taken from
     the action cache when present (the only time `tar` runs is when the cache truly lacks it);
  2. `build --no-remote-cache toolchains//:{llvm,sysroot,ndk}_verified`: an uncached worker action that hashes
     EVERY byte, mode bit, symlink and name of that very tree against the checked-in manifest
     (`toolchains/*.manifest`, gate files). Exit 0 only if tree and manifest are identical.

Buck2 keeps the tree of step 1 in the daemon, so the build that follows consumes the digest step 2
verified; in a daemon that already ran both, neither re-executes anything. Any difference (forged, extra,
missing or altered member) makes step 2 fail: there is never a silent re-fetch. The `toolchain` gate
(grade_toolchain) runs this first and reports it; `grade_build.run_buck` re-primes the fresh daemon of a
later gate the same way. Both steps cost seconds when the daemon is warm.
"""

import re
from dataclasses import dataclass

CACHED_TARGETS = ["toolchains//:llvm_ref", "toolchains//:sysroot_ref", "toolchains//:ndk_ref"]
VERIFY_TARGETS = ["toolchains//:llvm_verified", "toolchains//:sysroot_verified", "toolchains//:ndk_verified"]
MANIFESTS = ["llvm.manifest", "sysroot.manifest", "ndk.manifest"]   # in the toolchains cell, same order as VERIFY_TARGETS
PLATFORM = "toolchains//:linux_release"
VERIFY_CATEGORY = "verify_tree"
STEP_FETCH, STEP_VERIFY, STEP_WHAT_RAN, STEP_CACHED = "fetch", "verify", "what-ran", "verify-served-from-cache"
_TAIL = 3000
_DIFFERENCE = re.compile(r"^\s*(missing|extra|changed): (.+?)(?: \(manifest .*)?$", re.MULTILINE)
_ACTION_EXIT = re.compile(r"exit code (-?[0-9]+)")


@dataclass(frozen=True)
class Failure:
    """Why the toolchain trees of a daemon are not the verified ones."""
    step: str       # STEP_*: which of the commands said no
    code: int       # exit code of that buck2 command (0 for STEP_CACHED)
    stderr: str     # its stderr (for STEP_CACHED: the what-ran line)

    def message(self):
        return ("TOOLCHAIN VERIFICATION FAILED (%s, exit %d): the cached toolchain tree is not byte-identical "
                "to toolchains/*.manifest, or could not be checked. Not re-fetching.\n%s"
                % (self.step, self.code, self.stderr[-_TAIL:]))

    def manifest(self):
        """The manifest whose verify action failed (the first one buck2 names), or None."""
        named = [(self.stderr.find(t.split(":")[-1]), m) for t, m in zip(VERIFY_TARGETS, MANIFESTS)]
        named = sorted((position, m) for position, m in named if position >= 0)
        return "toolchains/" + named[0][1] if self.step == STEP_VERIFY and named else None

    def first_difference(self):
        """The first path the verifier reported as missing, extra or changed, or None."""
        match = _DIFFERENCE.search(self.stderr) if self.step == STEP_VERIFY else None
        return match.group(2) if match else None

    def verifier_exit_code(self):
        """The exit code of the verify action itself, as buck2 reports it, or None."""
        match = _ACTION_EXIT.search(self.stderr) if self.step == STEP_VERIFY else None
        return int(match.group(1)) if match else None


def needs_verification(args):
    """True for a `buck2 build` that disables the remote cache."""
    return bool(args) and args[0] == "build" and "--no-remote-cache" in args


def prepare(run, tree):
    """Run the two steps with `run(tree, args) -> (code, out, err)`. None if verified, else a Failure."""
    base = ["build", "--target-platforms", PLATFORM, "--materializations", "none"]
    code, _, err = run(tree, base + CACHED_TARGETS)
    if code != 0:
        return Failure(STEP_FETCH, code, err)
    code, _, err = run(tree, base + ["--no-remote-cache"] + VERIFY_TARGETS)
    if code != 0:
        return Failure(STEP_VERIFY, code, err)
    code, out, err = run(tree, ["log", "what-ran"])
    if code != 0:
        return Failure(STEP_WHAT_RAN, code, err)
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and "(%s " % VERIFY_CATEGORY in fields[1] and fields[2] == "cache":
            return Failure(STEP_CACHED, 0, line)
    return None
