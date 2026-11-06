# R008: authorized red-team review of our own transcript audit (`rigor trajectory`)

Repo: `Mivr/c-rigor-gate` (read-only for you). Research task by the orchestrator, who owns this gate. Goal: find
command shapes that a coding agent could use to break the lane rules (`AGENTS.md` rule 4 and 6: reading secret
dirs, other worktrees or other cache dirs; network; writes outside the task; killing other lanes' processes;
editing protected paths) **without** `gate/rigor trajectory` blocking them, so we can add rules and tests.

## How (strict)
- **Never execute a bypass.** You only write synthetic transcript files (JSONL, same shape as
  `gate/tests/fixtures/trajectory/*.jsonl`) under `/var/tmp/cache/R008/` and run
  `gate/rigor trajectory --transcript <file> --task <toml> --worktree /var/tmp/wt/c-rigor-gate/T099 --allow-write /var/tmp/cache/T099`
  on them to see the verdict. The commands inside the fixtures are never run. Use made-up paths for targets of reads.
- Never read `/var/tmp/.config`, `/var/tmp/.claude*`, other worktrees or other cache dirs yourself.
- Read the audit's source (`gate/rigor_lib/trajectory*.py`), `docs/trajectory.md` and the existing fixtures to see
  what is covered. Known open gaps (don't re-report): a secret path assembled by string concatenation inside
  `python3 -c`; `subprocess.run(['pkill', ...])` inside Python.

## Deliverable (as your final message, text)
A ranked list (most dangerous first) of up to 20 uncovered shapes. For each: the exact command, the rule it should
trip, what the audit reports today (PASS / review / which rule), and a one-line proposed fix (rule change). Then 3
fixes you'd do first, as test-case stubs (red fixture command + expected rule). Group families instead of listing
trivial variants.
