# Schema mutation engine prototype: measurements (T124, 2026-11)

v1 (`c_mutants`) against the schema engine (`c_mutants_schema`, `docs/mutate-schema.md`) on five business-apps modules, built
from the product clone at gate commit of branch `task/T124`, `--no-remote-cache`, RE farm shared with other work, each
build once, cold (no action cached; the unmutated toolchain fetch is not counted). Numbers come from the Buck2 event logs
(`mutate/schema/schema_measure.py`). **CPU seconds are not in the event log** (RE gives no instruction counts); "exec s" is
the action's execution time on the RE worker (workers have 1 CPU, so it is the nearest figure). "wall s" is the sum of the
actions' own wall times (includes input materialisation, queueing); "build wall" is the whole `buck2 build`.

## Totals per module

| Module | Engine | Actions executed | Action wall s | Exec s | Build wall s |
|---|---|---:|---:|---:|---:|
| lib/ds/fmap | v1 | 46 | 486 | 456 | 30 |
| | schema | 41 | 1409 | 1377 | 677 |
| lib/fmt/jpull | v1 | 128 | 592 | 387 | 58 |
| | schema | 102 | 967 | 859 | 236 |
| apps/lockers/relay/frame | v1 | 61 | 155 | 92 | 26 |
| | schema | 51 | 96 | 62 | 36 |
| apps/lockers/lk/audit | v1 | 127 | 442 | 214 | 47 |
| | schema | 101 | 277 | 144 | 52 |
| lib/io/posix_fs | v1 | 197 | 4284 | 3828 | 739 |
| | schema | 141 | 3552 | 3203 | 1130 |

The totals include steps 1 to 3b, which both engines run identically (mutant list, standalone compile of every mutant,
`-O0` compiles): about 20 to 100 exec s per module.

## The run stage alone (v1 `mutant_run` against schema link + reach + kill + gen)

| Module | v1 run actions | v1 exec s | schema run-stage actions | schema exec s | of which kill actions (count, exec s) |
|---|---:|---:|---:|---:|---|
| fmap | 16 | 429 | 12 (+4 baseline) | 1342 | 4, 1336 |
| jpull | 47 | 307 | 43 (+14) | 786 | 14, 775 |
| frame | 23 | 65 | 14 (+6) | 36 | 6, 33 |
| audit | 46 | 151 | 34 (+10) | 85 | 10, 78 |
| posix_fs | 59 | 3683 | 31 (+13) | 3082 | 13, 3073 |

("+n" = the baseline link and run per test that both engines make; v1's count includes them.)

## Mutants and runs (schema report summaries)

| Module | Mutants listed | v1 would run | Schema-eligible | Not eligible (reason) | schema-unviable | Unreached | Kill runs made | Of which after the first kill (v1's stop rule would skip) | Runs v1 makes without the stop rule |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| fmap | 196 | 166 | 166 | none | 0 | 0 | 585 | 338 | 664 |
| jpull | 448 | 394 | 394 | none | 0 | 0 | 3926 | 3229 | 5516 |
| frame | 246 | 214 | 214 | none | 0 | 0 | 398 | 184 | 1284 |
| audit | 496 | 449 | 440 | 9 constant-context | 0 | 0 | 1723 | 1122 | 4400 |
| posix_fs | 679 | 566 | 566 | none | 0 | 0 | 3682 | 2453 | 7358 |

(Unreached mutants: none on these modules; `unreached` is used in the self-test, 11 in `elig`. Schema compiles: 1 per source
unless bisection was needed; none was needed on these modules. In the self-test module `elig`, bisection found 2 offenders
in 16 compiles.) "v1 would run" = mutants that are not unviable, `equivalent` or `duplicate`. `baseline_reproduced`: the reach
run reproduced v1's unmutated run record for every test of every module.
Classes (schema): fmap 147 killed-assert 19 killed-crash; jpull 387/7; frame 211/2 and **1 survived**; audit 431/9;
posix_fs 510/47 and **9 survived**.

## Class disagreements v1 against schema (eligible mutants only)

| Module | Compared | Agree | Disagree |
|---|---:|---:|---:|
| fmap | 166 | 165 | 1 |
| jpull | 394 | 394 | 0 |
| frame | 214 | 214 | 0 |
| audit | 440 | 438 | 2 |
| posix_fs | 566 | 565 | 1 |

All four are **kill against kill** (no survivor became a kill or the reverse); every survivor of v1 survives in the schema:

* fmap `fmap.c:102` arithmetic `&` -> `|`: v1 killed-assert, schema killed-crash.
* audit `parse.c:31` function-body of `skip_spaces` (returns NULL), `parse.c:101` relational `<` -> `<=` in `summary_field`: v1
  killed-assert, schema killed-crash. In the same test (`audit_parse_digits_test`) v1 reports a failed check and the
  schema a fatal signal. The mutants make the code read through a null or out-of-range pointer; where the process dies
  or which check fails first depends on the compiled code and memory layout, which differ between a standalone mutant object and the
  switchable schema (undefined behaviour territory, the divergence P003 5.3 audits).
* posix_fs `ops_at.c:36` return-value in `open_existing`: v1 killed-crash, schema killed-assert (the reverse).

None is explained by construction (`schema_compare` calls it unexplained; the task does not fail on business-apps). They
matter for W2 only if `killed-assert` against `killed-crash` is used (`crash-kill-ratio`, per-function assert-kill rule):
the same mutant can flip class. All four are kills in both engines.

## Decision for P003 W2

**Conditional go.** The mechanism works on first contact: 1780 schema-eligible mutants on five modules, all baselines
reproduced, no mutant lost, the class agrees on 1776 and the other four are kill-against-kill, one schema compile per source
and one link, one reach and one kill action per test replace 16 to 59 relinking actions. But the prototype as built is **not
faster**: summed exec time is lower on three modules (frame -32 %, audit -33 %, posix_fs -16 %) and higher on two (jpull
+122 %, fmap +202 %), and build wall time is higher on four of five (fmap 677 s against 30 s, jpull 236 against 58, posix_fs
1130 against 739) because one kill action per test serialises what v1 spreads over 64 slots. Two numbers decide it: (1) 46 to
82 % of the kill runs made (`kill_runs_after_first_kill`: 3229 of 3926 on jpull, 1122 of 1723 on audit) come after the
mutant was already dead; P003 keeps v1's stop at the first kill, which is what turns the schema engine from slower into
faster on jpull and fmap (scaling the kill time by the runs kept gives about 140 s for jpull against v1's 307 and about 565 s
for fmap against 429, an estimate: this prototype did not implement the stop); fmap stays worse because its tests are slow
and pay for the switch in every site; (2) wall time needs the kill actions split into chunks
(`kill_chunk`) or by test group: W2 must shard, and should keep the schema-eligible kills at 100 % of the v1 verdicts
(the four disagreements are still kills). Build W2 with the stop rule and sharding; re-measure fmap and jpull first, and
do not count on more than 1.5x to 2x on modules whose tests spend their time in the mutated code.

## Not measured / caveats

* One build per cell, shared RE farm: wall times carry queueing noise; exec s is steadier. No repeat was made (rule 7).
* CPU seconds: not available (see above). Exec time on a 1-CPU worker is the stand-in.
* The first v1 fmap build included the toolchain fetch and was repeated with a comment appended to `fmap.c` (a cold key) for the row above.
