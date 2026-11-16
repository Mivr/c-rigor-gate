# U23: the lockers event catalogue, its abstraction key, and the first real exploration with judges

Repo `Mivr/c-rigor-gate`, branch `task/U23`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `docs/ui-explore.md` in
full; `docs/ui-judges.md`; `docs/ui-contract.md`; `plan/P004-visual-gate.md` 4.3 (strategies, bounds, coverage) and
3.7; `selftest/ui_product/toy.events.toml` as a format example. Read only, in
`/var/tmp/wt/business-apps/U04a` (a checkout of business-apps at its integration branch; you build there, you never
edit there): `docs/lockers/ui-model.md` in full (the adapter: boot seeds, the environment catalogue, ambient
measurements, known gaps), `docs/lockers/ui-rules.md`, `docs/lockers/ui-look.md` as needed,
`apps/lockers/lkapp/uimodel/tests/*.in` (how real sessions reach each screen).

## Why
Every piece of the UI gate so far was proven on toys, canaries and 23 hand-recorded frames. Nothing has yet explored
the real kiosk. This task writes the kiosk's event catalogue and key and runs the explorer with the `ui-scene` and
`ui-fit` judges on the real probe, and reports what the machine finds, what it costs, and where the gate or the
adapter is still wrong.

## Do
1. `products/business-apps/ui/lockers.events.toml` (`ui-events/1`). It is an owner-sealed file: you DRAFT it; every
   row carries provenance to a product spec line or adapter doc line; the header says "DRAFT by the U23 agent,
   unsigned, for the owner's review". Content:
   - `requires` all seven capabilities (`pointer` included); `drain_ms` <= 60000 (the adapter's trace must be fetched
     at least every 60 virtual seconds); `max_wait_ms` covering the longest product timer (the 5 min report);
   - `[ambient]`: `trace = ["touch"]` (provenance: the adapter doc's ambient table / uiloop), and
     `countdown_restart_role = "countdown"` (provenance: ui-rules report timer; the adapter doc's reading of
     fold_core/session.c). Do NOT declare `due_restart_ms`;
   - u1: every intent the scenes publish (digits, backspace, enter, sizes, done, dismiss, language, staff actions),
     each with `expect`; u2: taps on the real controls of each screen class; u3: complement taps (blank points, under
     a modal scrim, a disabled size); u4: code macros per boundary class through pad and wedge, using only the FAKE
     codes the adapter's fixtures define (no real code, token or address anywhere); u5: language; e1: every
     environment id the adapter lists (2-15, 20-25, 30-34, 40, 41, 50, 51) with its expect; t1: fire-due, before-due,
     until-change and the product timers;
   - boot: the healthy boot seed and the fault-profile seeds the adapter doc defines, as the explicit seeds you run.
2. `[key]`: the abstraction key. Start from the adapter doc and U06's note "The abstraction key (an engine limit)".
   It must separate screen classes, notice stacks, language, entered-digit count class and selection, and must NOT
   contain countdown values or absolute times. Show with `key-too-coarse` / `depth-unsaturated` / `model-nondeterministic`
   findings (or their absence) that it is neither too coarse nor exploding; give the state counts per depth.
3. Runs, each through `gate/rigor ui-explore` with `--judges ui-scene,ui-fit --contract
   products/business-apps/ui/lockers.toml --today 2026-11-16`, on the release probe built in the business-apps
   checkout (`gate/tools/buck2 build` there for the probe target the adapter doc names; the checkout pins a gate
   revision whose probe protocol is the same as yours):
   - a sweep per boot seed; a bfs on the healthy seed to the largest depth that fits a 20 min budget on this host,
     and a second, smaller bfs to show the count is stable; a walk with at least 3 walk seeds; replay of one found
     path (same finding id).
   - Record for each: command line, exit code, wall time, states, steps, findings by id and severity.
4. Triage EVERY distinct finding (group by id + target): one of
   - product defect (say which of the known ones it is: licences line clipped; dead banner tap-outside; `?40`
     storage-fault label; snackbar position and capturing scrim; stacked banners over BG/EN; or NEW, with the path,
     the state, the evidence and a reader's check of it in the recorded frame);
   - contract gap or pending owner decision (which row / question);
   - catalogue mistake (fix the catalogue and rerun);
   - gate defect or false positive (explorer or judge: minimal reproduction as a path file; do NOT change gate code);
   - adapter gap (what the adapter would have to provide).
   A finding you cannot classify is listed as unclassified with what you tried. Do not add exceptions to the
   contract and do not edit `products/business-apps/ui/lockers.toml`.
5. `docs/ui-lockers-first-run.md`: the catalogue's coverage (which screens and which of the 13 screen classes were
   reached, which were not and why), the run table, the triage table, the cost, the limits (render-only differences
   are not keyed; no view-domain enumerator; what `--require` coverage classes could be demanded today), and a short
   list of the changes that would most raise what the machine finds.
6. A loader test: `gate/tests/test_ui_lockers_catalogue.py` loads the catalogue and the contract together and asserts
   the structural facts that must not rot (schema, requires, ambient declaration, every e1 id of the adapter list
   present once, no `due_restart_ms`). It does not run the probe.
7. If the explorer refuses the real probe or dies (exit 2, a protocol error, a timeout), that is the result: report
   the exact output and the smallest reproduction, then continue with whatever still runs.

## Paths
`products/business-apps/ui/lockers.events.toml` (new), `docs/ui-lockers-first-run.md` (new),
`gate/tests/test_ui_lockers_catalogue.py` (new), `tools/affected.toml` only if a new file matches no rule. Evidence
and findings files stay under `/var/tmp/cache/U23/` (not committed); the doc quotes what matters. No gate code, no
other file under `products/`, nothing in business-apps.

## Acceptance (the orchestrator re-runs)
- The loader test and `python3 -I -B gate/tests/run_parallel.py` at the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group` only).
- `python3 -I tools/affected.py --check`.
- The sweep on the healthy seed and the replay, re-run by the orchestrator from the command lines in the doc, give
  the documented exit code and finding ids.

## Report
The run table, the triage table, what you could not reach or classify, every deviation. Your report is not evidence.
Never kill a process by name; scratch and `TMPDIR` under `/var/tmp/cache/U23/`; explorer runs under
`timeout`/`--budget-s`; at most 2 heavy processes at once (4 shared CPUs).
