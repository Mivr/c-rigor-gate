#!/bin/bash
# Regenerate toolchains/*.manifest from a REAL unpack of the pinned archives.
#
#   toolchains/gen_manifests.sh            (from the repository root; needs the RE farm)
#
# The trees are built with --no-remote-cache from a stopped daemon, so `tar` really runs on a
# worker on the sha256-pinned download and nothing planted in the action cache can reach the
# manifest. The output is deterministic: running it twice must leave `git diff` empty.
# Review any change to a manifest line by line: it is the root of trust of every cached toolchain.
set -euo pipefail
cd "$(dirname "$0")/.."
tools/buck2 kill >/dev/null 2>&1 || true
tools/buck2 build --no-remote-cache --materializations all toolchains//:llvm toolchains//:sysroot toolchains//:ndk toolchains//:android_build_tools toolchains//:android_platform toolchains//:jdk --show-output |
  while read -r label path; do
    case "$label" in
      toolchains//:llvm) name=llvm ;;
      toolchains//:sysroot) name=sysroot ;;
      toolchains//:ndk) name=ndk ;;
      toolchains//:android_build_tools) name=android_build_tools ;;
      toolchains//:android_platform) name=android_platform ;;
      toolchains//:jdk) name=jdk ;;
      *) continue ;;
    esac
    python3 -I toolchains/verify_tree.py gen "$path" > "toolchains/$name.manifest.new"
    mv "toolchains/$name.manifest.new" "toolchains/$name.manifest"
    echo "$name: $(wc -l < "toolchains/$name.manifest") lines"
  done
tools/buck2 kill >/dev/null 2>&1 || true
