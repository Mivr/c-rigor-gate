# Phase 1: a trustworthy C gate, proved on annas-c

Agreed with the owner 2026-11-06. Product used to prove the gate: [Mivr/annas-c](https://github.com/Mivr/annas-c).

## Principles
- **The gate is built before the product.** An unverified gate only measures how well agents game it.
- **Separation:** this repo decides pass/fail; product repos only contribute source directories.
- **Fail closed:** a crash, timeout, missing result or skipped gate (`NOT_RUN`) is a FAIL.
- **Every gate ships with a canary** that must turn it red.
- **Loosening is signed** by the owner/orchestrator key and stored outside the product repo. A text line in the
  repo is never a sign-off (this closes the gap found in club-apps' `ratchet.py`, where any agent could write
  `# orchestrator sign-off:` itself).
- **Model diversity:** Sonnet implements; Opus reviews gate code, writes hidden tests and red-teams.

## Grading tree (the interface between gate and product)
The gate driver assembles a fresh directory per grading run:
- `gate/` = this repo, checked out at the commit the **gate** pins (not whatever the product carries);
- the product's declared source dirs (`<module>/src`, `<module>/include`, `<module>/BUCK`, `<module>/tests`);
- a gate-owned `.buckconfig`, toolchain cell and flag profile. The product's own `.buckconfig`, `tools/` and
  any copy of the gate it carries are ignored.

Product `BUCK` files may only `load()` from `gate//rules`. The macros take no compiler flags.

## Steps
| # | Task | Engine | Gate it delivers |
|---|---|---|---|
| T001 | Hermetic C toolchain on Buck2 + RE, 4 modes, macros skeleton | Sonnet | `-Werror` sealed profile, sanitizers, MC/DC coverage, fuzz |
| T002 | `ctest` framework + gate driver kernel | Sonnet, Opus line review | contracts/allowed paths, expected-test-ID list (missing = fail), test-count ratchet, assertion-free test check, suppression scan, signed sign-offs, `verdict.json` |
| T003 | Canary pack + tripwires | Sonnet (canaries), Opus (review) | gate integrity: each canary must be red |
| T004 | Mutation testing for C | Opus design, Sonnet build | zero survivors; TCE drops equivalents; Mull as cross-check |
| T005+ | annas-c modules under the gate | Sonnet | core, json, html, url+sanitize, transport port + libcurl adapter, annas, cli, mcp |
| T0xx | Hidden tests for annas-c (private `c-rigor-hidden`) | Opus | fail-on-base / pass-on-head |
| T0xx | Red team | Opus | every successful cheat becomes a canary |

## Exit criteria
- annas-c v1 passes the full gate: download by md5, search via a fixture-tested parser with a clear
  "browser verification required" error on DDoS-Guard challenges, article lookup, MCP stdio server.
- All canaries red, all tripwires red; red team 0 successes over N attempts.
- Warm gate run <= 30 s with 0 re-executed actions.

## Known limit (accepted by the owner for phase 1)
Contributor subagents run as the same uid as the orchestrator, with the same filesystem and credentials.
Hidden tests and secrets are therefore protected by **detection**, not enforcement: hidden tests are fetched
only at grading time, decoy files are planted, and the orchestrator checks every agent transcript for
forbidden reads, `gh`/network calls and writes outside the contract. Moving contributors to separate-uid,
no-network sandboxes (orca-dev on sb-ws) is phase 2.
