# T026: trajectory false blocks on four more real gate transcripts (backlog B22)

Repo: `Mivr/c-rigor-gate`. Branch `task/T026`. Read `AGENTS.md`, `docs/trajectory.md`, `gate/rigor_lib/trajectory*.py`,
`gate/tests/trajectory_real.sh`, and how T019/T020 handled B20/B21. **T013, T023 and T025 run in parallel**: touch
only the paths below.

## Why
The orchestrator's audits of T021, T022 and T024 (real transcripts, staged key-free in `/var/tmp/cache/T026/real/`)
FAILED on benign behaviour. Every block a reviewer must wave through trains reviewers to ignore blocks.
1. **`secret-env-access` on `${!prefix*}`** (T024, 4 blocks): `cp "${!r1_*}" /dev/null` inside a selftest heredoc.
   Bash indirect name listing in script text the agent is writing, not reading an env secret.
2. **`malformed-entry` on a failed tool call** (T021, 1 block): a `Write` whose input used `file_text` instead of
   `content`; the tool rejected it and wrote nothing. Classify a rejected call by its own tool_result (error, nothing
   written), keep it visible as review, never pass it silently, and still block if the path would have been outside.
3. **`write-outside` on the agent's own grade work dir** (T022, 2 blocks): `chmod -R u+w $W; rm -rf $W` where
   `W=/var/tmp/rigor-grade.XXXXXX` was created by the agent's own `selftest/grade.sh` run (`RIGOR_GRADE_KEEP=1`)
   earlier in the same transcript. Recognise a path the transcript itself proves the agent's own run created
   (printed by a gate script it ran, under `$TMPDIR`), and only that; another task's dir stays a block.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/tests/test_trajectory*.py`, `gate/tests/fixtures/trajectory/**`,
`gate/tests/trajectory_real.sh`, `docs/trajectory.md`, `plan/backlog.md` (add B22 and mark it).

## Requirements
1. Each of the three becomes non-blocking with a minimal, named rule, and each gets a red twin that must stay a block:
   `${!SECRET*}`/`${!ANNAS*}` expanded in a command the agent runs (not in text it writes), a rejected Write to a path
   outside the allowed set, `rm -rf` of a `rigor-grade.*` dir the transcript never shows the agent creating.
2. Trimmed fixtures from the real transcripts (only the lines needed; no system prompt text) in
   `gate/tests/fixtures/trajectory/`.
3. Run all four real transcripts (`real/*.jsonl`) and report block and review counts before and after, per file.
   `T011-gate.jsonl` passed before and must still pass.

## Acceptance
```sh
TRAJECTORY_REAL_DIR=/var/tmp/cache/T026/real gate/tests/trajectory_real.sh
selftest/gate.sh
```
