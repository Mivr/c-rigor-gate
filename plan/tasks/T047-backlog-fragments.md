# T047: a backlog that never conflicts (speed-up R007 #1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T047`. Read `AGENTS.md` ("Working efficiently") first.
`plan/backlog.md` is one markdown table edited by many tasks; it caused most merge-conflict fix-ups (R007).
Replace it with one file per row, folded into the table by a tool, so two tasks never edit the same file.
**In flight in parallel:** T038, T049, T050, and batch3 (T032 marks B1-B3 in `plan/backlog.md`). Touch none of their
files except the backlog move described here.

## Allowed paths
new `plan/backlog.d/` (one file per row), `plan/backlog.md` (becomes generated), new `tools/backlog_fold.py`, new
`gate/tests/test_backlog_fold.py`, `AGENTS.md` (one rule line), `tools/affected.toml` (a rule for the new paths only),
`docs/lanes.md` (a short "Backlog" note).

## Requirements
1. `plan/backlog.d/B<N>.md`: one file per row, holding the four cells (gap, found by, planned fix, and the row id
   from the file name) in a simple stable format you define (e.g. `found_by:` / `fix:` header lines then the gap
   text). Plus `plan/backlog.d/_header.md` for the title and table header.
2. `tools/backlog_fold.py` (stdlib, `python3 -I`): writes `plan/backlog.md` from the fragments, rows sorted by
   number; `--check` exits 1 if `plan/backlog.md` differs from the fold (and prints the diff); refuses duplicate
   ids, gaps in the format, and a `|` or newline inside a cell that would break the table. Idempotent.
3. **Byte-for-byte**: folding the fragments you create from today's `plan/backlog.md` reproduces it exactly (write
   a one-off splitter, run it, don't commit it). Test it.
4. `AGENTS.md` (Hard rules or Working efficiently): "Never edit `plan/backlog.md`; add or edit
   `plan/backlog.d/B<N>.md` and run `tools/backlog_fold.py`." `gate/tests/test_backlog_fold.py` includes a test
   that `--check` passes on the repo, so a hand edit of `plan/backlog.md` fails `selftest/gate.sh`.
5. New row ids: the orchestrator assigns them in the task spec; document that in `docs/lanes.md`.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_backlog_fold.py'
python3 -I tools/backlog_fold.py --check
python3 -I tools/affected.py --check
selftest/gate.sh
```
