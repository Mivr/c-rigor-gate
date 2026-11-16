# U05d: an ambient countdown restart, so a touch that restarts a visible countdown is not a tap effect

Repo `Mivr/c-rigor-gate`, branch `task/U05d`. Read first: `plan/tasks/U00-ui-gate-rules.md`; `docs/ui-explore.md`
("Taps", "Ambient events", the findings table); `gate/rigor_lib/ui_explore_catalogue.py` (`_ambient`),
`gate/rigor_lib/ui_explore_words.py` (`changes`, `ambient_split`, `tap_ambient`), `gate/rigor_lib/ui_explore_judges.py`,
`gate/tests/test_ui_explore_taps.py` (`AmbientTest`), the explorer stub and its modes (`pnotouch`, `ptwice`, `pchange`,
`prestart`), `selftest/ui.sh`. Read only: `/home/user/business-apps/docs/lockers/ui-model.md`, section "Ambient".

## Why
Measured on the real kiosk (business-apps U04f): on the end-of-shift report every touch restarts the report's 5-minute
deadline. This is intended (ui-rules: report 5 min with a countdown; the core handles `touch` only in that phase). It
shows as a patch on the countdown node (`update 6 text 298 сек 300 сек`), a semantic text difference of that node and
a frame difference of that label. It does not show in `next-due` (the 250 ms tick is nearer), it restarts to the last
tick + 300000 rather than to the tap's instant, and it is visible only when the displayed seconds change. So neither
`trace` nor `due_restart_ms` can express it, and under today's rule every complement or root tap on that screen is a
false `noop-tap-effect`, and a non-root tap with no intent is `ok` instead of `missed`.

## Do
1. Catalogue: `[ambient]` gains an optional pair `countdown_restart_role` (a scene role name, same pattern as roles
   elsewhere) and `countdown_restart_provenance` (checked by `ui_contract.check_provenance`); they go together; they
   need `trace` as today. Loader errors as for the other ambient keys.
2. Rule, in a tap step only, after the ambient trace records are set aside. The residual change of the step is a
   DECLARED RESTART, and then counts as "changed nothing", iff ALL of:
   - every new patch is `update <key> text <old> <new>` on a node whose semantic role, before and after, is the
     declared role;
   - the semantic trees differ only in the label field of those same keys (every other field of those nodes and every
     other node byte-identical; no node added or removed);
   - where frame records are compared (amended after review 1; a `region` hash covers the pixels inside a node's box,
     so every node whose box covers the countdown changes its region and the whole-frame crc with it): there is no
     `life` line and no change of the `lvprobe` count; each restarted key matches exactly ONE walk index (its `label`
     record shows the old text before and the new after, same class before and after; an ambiguous match rejects);
     of that index, the `node` record may differ only in x1, y1, x2, y2, the `label` record only in dotted, lines,
     natural/laid w/h, text and full_text (font id, line_h, align, align_drawn, long identical), `fit` and `region`
     freely; of any other index only the `region` record may differ, and only if its `node` record is unchanged and
     its box intersects the countdown's box (before or after); the `frame` line may differ in crc only;
   - every patched key has a semantic label difference, and its patches form a chain (first old = semantic old, each
     old = the previous new, last new = semantic new, after unescaping); a digit run longer than 18 rejects;
   - for each such node, old and new label each contain exactly one run of decimal digits, the text around the run is
     identical, and new value >= old value (a restart never skips a countdown forward);
   - no other new trace record and no `next-due` change other than a declared `due_restart_ms`.
   Anything else stays a change exactly as today. Equal old and new values cannot produce a patch; do not special-case.
3. A step that used the rule records it: a new INFO finding `ambient-restart` (key before, word; evidence: word, node
   keys, old and new values). Amended after review 1: one finding per restarted node, identity
   ["restart", key before, node key], the word in `observed`; no private `seen` set: the ordinary dedupe keeps one per
   id, shortest path first. Add
   it to the findings table and to the judges' id list. With the rule applied, a u3/root tap is judged as refused/no-op
   and a u2 tap on a non-root node with no intent is `intent-missed`, as on any other screen.
4. Gaming resistance, to state in the doc and prove by tests: the rule can hide only a text change of a node of the
   declared role whose number does not decrease, on a tap, in a catalogue whose sealed `[ambient]` declares it with
   provenance. A product cannot hide a navigation, a new node, a style or flag change, a countdown that jumps
   forward, or a change on a wait/event step.
5. Stub modes and tests (`AmbientTest` or a sibling; keep the file under 500 lines, split if needed): restart accepted
   (info, no `noop-tap-effect`); forward skip rejected (`noop-tap-effect`); restart plus another node's patch
   rejected; restart on a node of another role rejected; the same change without the declaration rejected; restart on
   a non-tap step is an ordinary change; label with two digit runs or changed surrounding text rejected; the
   `intent-missed` case above. Each new check must be seen failing once with the rule disabled (say how in the report).
6. `selftest/ui.sh`: one step that runs the stub with the declaration and asserts the info finding and the absence of
   `noop-tap-effect`, and one with a forward skip asserting `noop-tap-effect`. Existing steps' expectations unchanged.
7. `docs/ui-explore.md`: the rule, the key, the finding, the gaming-resistance paragraph, and why `due_restart_ms`
   cannot express this case.

## Paths
`gate/rigor_lib/ui_explore*.py`, `gate/tests/test_ui_explore*.py`, the explorer stub and its fixtures under
`gate/tests/` and `selftest/` that the explorer already uses, `selftest/ui.sh`, `docs/ui-explore.md`,
`tools/affected` rules only if a new file needs one. Nothing under `products/`, `ui/`, `rules/`.

## Acceptance (the orchestrator re-runs all of it)
- `bash selftest/ui.sh` twice in a row, exit 0, tree clean after.
- `python3 -I -B gate/tests/run_parallel.py`: only the host baseline (the `ssh-keygen` errors and
  `test_job…test_the_deadline_kills_the_whole_process_group`); no `tests.test_ui_*` failure.
- `python3 -I tools/affected.py --check`.
- No file over 500 lines, no function over 50 lines in the touched Python.

## Report
What changed, the real output of each acceptance command, how each new check was seen failing, every deviation, and
anything you could not do. Never kill a process by name. Scratch under `/var/tmp/cache/U05d/`.
