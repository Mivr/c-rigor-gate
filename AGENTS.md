# Rules for coding agents (c-rigor-gate and every product graded by it)

These rules are mandatory. If a task conflicts with them, stop and report; do not work around them.

## Roles
- **Owner:** Mihail. Decides scope, holds the signing key for loosening any gate.
- **Orchestrator:** a Claude Opus session. Writes task contracts (`plan/tasks/T<NNN>-*.md`), re-runs acceptance,
  reviews gate code line by line, merges and pushes. Writes no product code.
- **Contributors:** coding agents, one task at a time, each in its own git worktree on branch `task/T<NNN>`.

## Hard rules for contributors
1. **Stay inside your contract.** Touch only the paths your task lists. A diff outside them is rejected whole.
2. **Never weaken a check.** Do not edit flags, thresholds, baselines, canaries, tripwires, expected-test lists,
   or tests you were not asked to write. Do not add `#pragma ... diagnostic`, `NOLINT`, `-Wno-*`,
   `__attribute__((no_sanitize))`, skips, retries or sleeps. If a check is wrong, say so in your report.
3. **Never special-case the grader.** No code that detects tests, fixtures, CI, the gate or file names to change
   behaviour. No hard-coded expected outputs.
4. **Stay out of what is not yours.** Do not read or list: `/var/tmp/.config/`, `/var/tmp/.claude*`, `~/.ssh`,
   other worktrees, other agents' logs, any `*-hidden` repo. Do not call `gh`, `git push`, or the network,
   except Buck2 fetching URLs pinned by sha256 that your task names. Do not push, merge or rebase `main`.
5. **Build only with Buck2** through `tools/buck2`. Tooling scripts are Python 3 **stdlib only**. Nothing gets
   installed (`pip`, `apt`, `cargo install`, `npm i -g` are forbidden). Missing tool: ask in your report.
6. **The filesystem:** only `/var/tmp` is writable. Use your worktree and `/var/tmp/cache/<task>` for downloads.
   Never write to `/` or `/data`.
7. **The RE farm is shared** (`grpc://forge.internal:9092`, concurrency 64). Don't loop builds pointlessly.
8. **Your report is not evidence.** The orchestrator re-runs every acceptance command. Report exactly what you
   ran and its real output, every deviation, and anything you could not do. Saying "done" for something
   not done is the worst possible outcome; an honest "blocked" is fine.
9. **Commit** to your task branch with clear messages. Never amend or force-push someone else's commits.

## C rules (products)
- C17, compiled only through the `gate//rules` macros. No raw `cxx_*` rules, no `compiler_flags`.
- Static memory or arenas handed in by the caller; no `malloc` outside the `core` arena module.
- Clock, randomness, environment, filesystem and network are injected ports. Pure core, thin adapters.
- Small functions (<= 50 lines), small files (<= 500 lines), no recursion, no VLAs, every return value checked.
- Tests go through the module's public header only. No `static` -> non-static just for tests.
