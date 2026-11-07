# R010: design per-lane isolation (B5), the structural fix that makes the transcript audit a second line

Repo: `Mivr/c-rigor-gate` (read-only for you). Design research for the orchestrator; the owner decides and owns the
infrastructure. No code is changed in any repo, and nothing on the machine is reconfigured.

## Context
- Contributor agents are Claude Code subagents of the orchestrator session. They share its uid (`ubuntu`, 1000),
  filesystem, environment and credentials (B5). Isolation today is **detective**: `rigor trajectory` audits each
  transcript after the fact (T015 through T062, with R008's 20 families fixed). Hardening a denylist has diminishing
  returns. R009's second red team was stopped, and from now on we prefer **preventive** isolation.
- The session runs in a container with cgroup `cpu.max` of 2 CPUs and `memory.max` of 8 GiB, no capabilities, seccomp
  filter mode 2, and `NoNewPrivs` 0. `/usr/bin/unshare` exists; `bwrap` and `firejail` do not. Builds use Buck2 with
  remote execution on a NativeLink farm (`forge.internal:9092`). Agents need: their worktree (rw), their cache
  dir (rw), the read-only source clones under `/var/tmp/src`, the gate tool trees, the RE endpoint, and nothing
  else: no GitHub, no `/var/tmp/.config`, no `/var/tmp/.claude*`, and no other lanes' dirs.
- The club-apps sibling project already runs contributors in throwaway `orca-dev` containers with the LAN
  blackholed, capabilities dropped, no Docker socket and no host home (see
  `/data/club-apps/orca-workspaces/club-apps/repo/Club-apps-work/CLAUDE.md` section 2, read-only). That is the
  reference the owner already trusts.

## Deliverable (final message, text, under 1,500 words)
1. **Options, ranked.** For example: (a) per-lane `orca-dev`-style containers launched by a harness (the agent
   CLI runs inside); (b) user namespaces via `unshare -r -m -n` from inside this container, if the seccomp
   profile allows it (check only with a harmless `unshare -r true`, and report what happens); (c) a separate uid per
   lane on the host, with ACLs; (d) anything better you find. For each: what it prevents (reads of secrets and
   other lanes, network except RE, kills of other lanes' processes, writes outside its dirs), what it needs from the
   owner (host changes, images, privileges), and its cost per lane (start time, memory, RE access).
2. **How the agent CLI fits.** Today a lane is a Claude Code subagent (the Agent tool) and cannot be moved into
   another sandbox. What changes if lanes become separate CLI processes (`claude -p` or an SDK runner) inside the
   sandbox: the result channel, how the transcript is collected for `rigor trajectory`, and how cost and token
   metrics flow to the dashboard sampler in `/var/tmp/metrics`.
3. **The audit's new role** once isolation exists: which `rigor trajectory` rules become redundant and which stay
   (tamper of protected paths, test rewrites, clean-room reads, conduct).
4. **A migration plan** in at most 6 steps, each one shippable, with the owner decisions it needs marked.

## Rules
Read-only. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, other worktrees or cache dirs. No network except
reading local docs. The only probes allowed are harmless capability checks that change nothing (`unshare -r true`,
reading `/proc/self/status`). Scratch dir: `/var/tmp/cache/R010`.
