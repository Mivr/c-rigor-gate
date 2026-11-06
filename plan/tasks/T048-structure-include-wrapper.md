# T048: `structure` scans a translation unit that only includes product code (annas-c `tests/kit.c`)

Repo: `Mivr/c-rigor-gate`. Branch `task/T048`. Read `AGENTS.md` ("Working efficiently") first.
T032 ran the wired `structure` gate on annas-c: 24 `structure-build-failed` findings, all test modules, all from
`annas/tests/kit.c`, whose whole content is a comment plus `#include "annas/tests/kit_impl.h"` (app/ compiles the
same kit into its own tests). `structure_scan.unit_facts` raises "no location of the dump names annas/tests/kit.c;
the scan would be blind" (structure_scan.py ~511), because the main file has no AST nodes.
**In flight in parallel:** T032 (merging: `grade_structure.py`, `grade_pipeline.py`, `rules/structure.bzl`,
`selftest/grade.sh`), T037 (`grade.py`, `grade_context.py`, `verdict_inputs.py`, `approvals.py`), T046
(`canaries/**` new dirs, `canaries/runner.py`). Touch none of them. Do not edit `plan/backlog.md`.

## Allowed paths
`gate/rigor_lib/structure_scan.py`, `gate/tests/test_structure*.py`, `gate/tests/fixtures/structure/**`,
`selftest/structure.sh` (new steps only), `selftest/structure_product/**` (new files only), `docs/structure.md`.

## Requirements
1. A unit whose main file has no dump location is accepted **only if** its text, with comments and whitespace
   removed, consists solely of `#include "..."` lines naming non-system files, and the dump has at least one
   location in each included file. The included files' functions are then scanned and reported under their own
   paths, as today; the main file is listed in `files` with its line facts.
2. Everything else stays a `ScanError` (blind): a main file with any other token (a declaration, a macro, a
   `#define`, a `#pragma`, an `#include <...>` of a system header alone, an `#include` of a file that produced no
   location), an empty main file, a main file the dump never names because the wrong file was scanned.
3. Facts must not double count: the same header included by many units yields its functions once per unit, as for
   any header today (do not change aggregation).

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_structure*.py'
selftest/structure.sh
selftest/gate.sh
```
With red tests for each case in 2 and a green fixture shaped like annas `kit.c` + `kit_impl.h`; plus a new
`selftest/structure.sh` step building a wrapper unit through the real rule.
