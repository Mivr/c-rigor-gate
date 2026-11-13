# c-rigor-gate

Gaming-resistant gates for C written by AI coding agents, built with Buck2 on remote execution.

The premise: an agent's green test run means nothing if the agent could have weakened the test, the flags,
the thresholds or the checker. This repo is the part the agent does **not** control. Products (for example
[annas-c](https://github.com/Mivr/annas-c)) are graded by assembling a fresh grading tree from the product's
source directories plus a sealed checkout of this repo at a pinned commit. Everything that decides pass/fail
lives here.

Registered products and the allocation deny list: [docs/products.md](docs/products.md).
Lessons from decoupling a real C codebase, and the gate rules they became (reusable by any product):
[docs/lessons-decoupling.md](docs/lessons-decoupling.md), [docs/decoupling.md](docs/decoupling.md).

Status: phase 1 under construction. See [plan/phase1.md](plan/phase1.md).

## What it provides (phase 1 target)

| Piece | Purpose |
|---|---|
| `toolchains/` | Hermetic LLVM + sysroot fetched by sha256; build modes `release`, `san` (ASan+UBSan+LSan), `cov` (MC/DC), `fuzz` (libFuzzer). Sealed flags applied last. |
| `rules/` | `c_library` / `c_binary` / `c_test` / `c_fuzz` macros: the only rules a product may use. No raw compiler flags. |
| `ctest/` | Tiny C test framework with fail-closed, machine-readable results. |
| `gate/` | Python (stdlib-only) driver: task contracts, test-integrity ratchets, suppression scan, signed sign-offs, verdict. |
| `mutate/` | Source-level C mutation testing, one Buck2 action per mutant. |
| `canaries/` | Known-bad patches; each must turn the gate red or the gate is reported compromised. |
| `tripwires/` | Impossible obligations on honest code ([docs](docs/tripwires.md)); a green tripwire means a blind checker. |

Background and evidence: [Mivr/ai-code-rigor](https://github.com/Mivr/ai-code-rigor) (rigor levels L0-L5),
[Mivr/lang-bench](https://github.com/Mivr/lang-bench) (C for agentic dev loops).

License: MIT OR Apache-2.0.
