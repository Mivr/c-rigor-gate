# T023: semantic facts in the `san` mode too; any release/san difference is a finding (backlog B3, half of B17)

Repo: `Mivr/c-rigor-gate`. Branch `task/T023`. Read `AGENTS.md`, `rules/facts.bzl`, `rules/c.bzl`,
`gate/rigor_lib/cscan.py`, `gate/rigor_lib/facts_semantic.py`, `gate/rigor_lib/facts_cmd.py`,
`docs/product-checks.md`. **T013, T021 and T022 run in parallel**: don't touch `gate/rigor_lib/grade*.py`,
`verdict*.py`, `approvals.py`, `product_layout.py` or `tools/lanes/**`. Wiring into `rigor grade` is a later task.

## Why
The semantic scan reads the `clang -E` output of the **release** compile only. Code under
`#if defined(__SANITIZE_ADDRESS__)`, `__has_feature(address_sanitizer)`, `__has_feature(undefined_behavior_sanitizer)`
or any other macro that differs between the modes (`NDEBUG`, `__OPTIMIZE__`) is invisible to it, yet the `san`
tests run it. A product can hide a `_Pragma`, an `__asm__`, a denied call or a test-only shortcut there (R001 R5).

## Allowed paths
`rules/facts.bzl`, `rules/c.bzl` (only to request the `san` twin of the facts; no flag changes), a new
`gate/rigor_lib/facts_modes.py`, `gate/rigor_lib/facts_cmd.py` (one subcommand or flag), `gate/rigor_lib/cli.py`
(only if a new command is needed), `gate/tests/test_facts_modes*.py`, `selftest/product_checks.sh`,
`selftest/product_checks_product/**` (or wherever its fixtures live), `docs/product-checks.md`,
`plan/backlog.md` (mark B3, and B17's san half).

## Requirements
1. **San facts on RE.** For every product `c_library`/`c_binary`/`c_fuzz`, a `<name>_facts_san` target scans the
   `clang -E` output of the `san` compile (same scanner, same compile command the san build uses), cached like the
   release facts. Units must match one to one; a missing or extra unit fails the build.
2. **Mode diff.** `rigor facts --modes RELEASE_DIR SAN_DIR` (or a new `rigor facts-modes`) compares the two per
   unit: every semantic item (pragma, asm, builtin, suppression comment that survived, denied identifier, the
   called-function set from the preprocessed text) present in one mode and not the other is a finding
   `mode-divergent-code` with file, line and the item. Symbol facts are not compared (the san object legitimately
   differs). Exit 0/1/2 like every gate; a unit present in one mode only is exit 2.
3. **The legit difference.** The gate's own sealed flags differ between the modes. Anything that comes only from the
   gate's toolchain headers or `-D` flags is not product code; product code under a mode macro is a finding at every
   level, with no policy knob. Document this choice.
4. Fails closed: unreadable facts, schema mismatch, or a module with no san twin is exit 2, never a pass.

## Self-test
In `selftest/product_checks.sh`: green (product with no mode-dependent code: 0 findings); red cases, each the only
finding: code under `__SANITIZE_ADDRESS__`, under `__has_feature(address_sanitizer)`, under `#ifndef NDEBUG`,
under `__OPTIMIZE__`, and the same hidden through a macro defined in a product header. Cold, then warm with 0
actions executed. Report cold and warm action counts.

## Also report (information only)
Run it over a scratch clone of `/var/tmp/src/annas-c` main (in your cache dir) and list the findings.

## Acceptance
```sh
selftest/product_checks.sh
selftest/gate.sh
selftest/grade.sh
```
