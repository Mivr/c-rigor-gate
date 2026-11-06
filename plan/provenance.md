# Commit provenance notes

- Contributor agents must pass their identity per commit (`git -c user.name=... commit`) and never write the
  repository git config. On 2026-11-06 contributor agents wrote `user.name` into the shared repository config, so
  orchestrator commits `a213cfa`..`2d0dacb` on `main` (merges `Merge T00N`, `plan:` and `gate:` commits) show the
  author "T003 contributor (Claude Sonnet)". They were made by the orchestrator. The history was not rewritten
  (already pushed; task branches were based on it). From `2d0dacb` onward the orchestrator commits as
  "Orchestrator (Claude Opus)", and the transcript audit flags any `git config` write.
