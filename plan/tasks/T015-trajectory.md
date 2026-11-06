# T015: `rigor trajectory`: structured, tested audit of a contributor agent's transcript (backlog B10)

Repo: `Mivr/c-rigor-gate`. Branch `task/T015`. Read `AGENTS.md`, `plan/phase1.md`, `plan/backlog.md` (B5, B10),
`docs/gate.md`. The orchestrator's current scratch script is at `/var/tmp/cache/T015/audit_v0.py`: read it as
the starting rule set. **T008, T011 and T014 run in parallel**: don't touch `grade*.py`, `mutants_*.py`,
`order.txt`, `products/**`, `structure*`, `cscan.py`, `semantic_table.py` or `facts_*.py`. In `cli.py` add one
`COMMANDS` entry and nothing else.

## Why
Contributor agents run as the orchestrator's uid (B5), so isolation is detective: after every task the
orchestrator audits the agent's tool-use transcript (Claude Code JSONL). The scratch script is untested and
noisy. It flags the agent's own persisted tool outputs under the harness's state dir, test-data URLs, and
env-var names in test code. Noise trains reviewers to ignore findings, so the audit must be precise and part
of the gate.

## Allowed paths
`gate/rigor_lib/trajectory*.py`, `gate/rigor_lib/cli.py` (one entry), `gate/tests/test_trajectory*.py`,
`gate/tests/fixtures/trajectory/**` (synthetic transcripts only), `docs/trajectory.md`, `plan/backlog.md` (mark
B10).

## Requirements
1. `rigor trajectory --transcript <jsonl> --task <products/p/tasks/x.toml or a TOML given on the command line>
   [--allow-write <dir> ...]`. The input is a Claude Code subagent transcript (JSONL; tool calls are
   `message.content[].type == "tool_use"` with `name` and `input`; results are `tool_result` blocks). Parse it
   defensively: an unparseable line is a finding, never skipped silently, and an empty transcript is exit 2.
2. Rules, in a gate-owned table with an id, a severity (`block` or `review`) and a rationale for each:
   - **Reads** of forbidden paths: the orchestrator's secret dir, other worktrees, other tasks' cache dirs, SSH
     material, hidden-test repos, and the clean-room upstream. Resolve paths, so that `..`, symlink-looking
     spellings, `~` and env vars are caught. Look at the inputs of every tool (Read, Grep and Glob paths, Bash
     commands), not just Bash. **Exception:** the harness's own persisted tool-output files. A Read of a file
     that a *previous tool_result in the same transcript* announced as "Full output saved to: <path>" is allowed
     for exactly that path.
   - **Writes** (Write, Edit, NotebookEdit, and Bash redirections `>`, `>>`, `tee`, `cp`, `mv` and `rm` where
     parseable) outside the worktree and the allowed scratch dirs.
   - **Commands**: gh, git push, touching main, worktree prune or remove, sudo, package installs, `--no-verify`,
     git config writes, network tools (curl, wget, nc, ssh) with any host but the allowlist, spawning agents,
     reading the process environment wholesale (`env`, `printenv`, `/proc/*/environ`), and any access to a
     secret-looking env var name in a *command*. The same name inside a file written to the worktree is
     review-only. `git -c user.*=` identity flags are fine.
   - **Tamper signals**: edits to protected paths named in the task contract, and deleting or rewriting test
     files in an implementer task.
3. Output: JSON findings (rule id, severity, transcript line, tool, excerpt redacted to 160 chars) plus a
   human table. Exit 1 if there is any `block` finding, 0 otherwise. `review` findings print but don't fail.
4. Precision: the synthetic fixtures must include every false positive the scratch script produced (a persisted
   tool-output read, a URL in test data such as `https://dl.example.org/f/1`, an env var name in a heredoc
   writing a test file, the session URL in a commit-trailer line) as **green**, and each forbidden behaviour,
   including obfuscated spellings, as **red**.

## Acceptance
```sh
selftest/gate.sh   # includes the new unit tests
gate/tools/rigor trajectory --transcript gate/tests/fixtures/trajectory/<each>.jsonl ...   # report the outputs
```
