# The `oracle` gate: byte-identical replay of the Rust viewmodel (T2G7, P330 §3)

P2 of the plan: the Rust `viewmodel/lockers`, driven by scripted fake ports, gives per step `{intent | port reply | tick} -> ViewState`
and the port calls it made. The C app replays the same inputs through its real wiring and the two texts must be **byte-identical**.
Half of the traces are hidden: the grader holds them (`rigor grade --oracle DIR`) and the implementer never sees them. This file is the
gate's side of the contract: the bundle, the `vm-trace/1` reader, the judge `rigor oracle` and its gate files. Producing real traces is
the club-apps tool `tools/vm-trace` (T2C1, T2C2), the real replayer the business-apps task T2B7; the gate has a fixture of both
(`selftest/sim/oracle/`).

## The bundle

```
<bundle>/oracle.toml
<bundle>/files/<trace id>.trace        # flat, one vm-trace/1 file per trace

product = "business-apps"              # must equal product.toml's name
origin = "T2C2"                        # the task or run that produced it (information)
produced_from = "<40-hex>"             # the club-apps commit the traces came from (information)
[trace."scripted-01"]                  # exactly one table per file, exactly these keys
sha256 = "<64-hex>"
steps = 12                             # the number of `in` lines
```

Every defect is exit 2 (`oracle_bundle.load`): a bundle that is a symlink or not a directory, an entry besides `oracle.toml` and
`files/`, a symlink, special file or sub-directory in `files/`, a file that `[trace]` does not list or the reverse, a wrong `sha256` or
`steps`, an unknown or missing key, a bad `produced_from`, a trace id outside `[A-Za-z0-9_][A-Za-z0-9_.-]{0,95}`, and any trace that is
not valid `vm-trace/1`. `rigor grade --oracle DIR` copies the bundle once (symlinks and special files refused while copying), loads
the copy and binds `inputs.oracle_sha256` = sha256 of the canonical JSON of `[[path, sha256], ...]` over `oracle.toml` and every
`files/...` entry, sorted (the witness bundle's scheme). It is checked against the product name before `clone`. The verdict holds
that hash, the ids and positions of findings, and nothing of any trace.

## `vm-trace/1`

JSON lines, one file per scenario, LF only, no empty line, compact (no spaces), keys in the order shown. The reader (`parse_trace`)
refuses everything else.

| Record | Keys, in order | Notes |
|---|---|---|
| `cfg` | `k v id src seed start_ms lang inventory codes pulse_units min_free_mb offline_age_ms` | first line, once; `v` is `vm-trace/1` |
| `in` | `k t op` and the keys of the op | `digit{d}`, `backspace`, `submit`, `scan{text}`, `choose{size}`, `cancel`, `dismiss{intent}`, `dismiss_report`, `ack_opened`, `lang{lang}`, `tick{adv_ms}`, `set_codes_offline`, `fail{port,count,err}` |
| `fx` | `k t port` and the port's own keys | one per port call made while handling the input, in call order; ports `opener.open`, `store.save`, `store.load`, `audit.append`, `codes.role_of`, `coils.read`, `volume.free_mb`, `sync.note`; `t` equals the input's |
| `vw` | `k t s` | after the input and its `fx`; `s` is the canonical ViewState text of `lk_view_canonical` |
| `ns` | `k t` | replayer output only, in place of `vw`: the input did not settle (`oracle-no-settle`); nothing may follow |

A trace is `cfg`, then any number of steps `in`, `fx`*, `vw`. The text of `s` is kept exactly as written, never parsed and written
back, so the comparison has no JSON-level tolerance. The Rust side may not contain `ns`. The op key names are the gate's reading of
P330 §3.2 (the names in its braces); a producer that differs is exit 2 until this table and the reader change together.

## The replayer's side

The product's gate-owned `oracle-policy.toml` names `replayer`, a `c_binary` that reads one trace on stdin and writes the replayed
one on stdout: the `cfg` and `in` lines as given and, for each input, the `fx` lines and the `vw` line of the C app (or `ns`). The
gate runs it over every trace of the bundle in one build action in the san platform (docs/grade.md, "The oracle gate in the pipeline")
and collects `<trace id>.trace` into the results directory that `rigor oracle` reads. The judge trusts none of the replayer's own claims.

## What "equal" means

For each trace and step, after the normalisation table (applied to the Rust and the C text alike):

1. the `cfg` line and the `in` lines are byte-identical (the replayer must replay the input it was given);
2. the ordered `fx` lines are equal, and the number of steps is equal;
3. the `vw` text `s` is byte-identical (this covers `countdown_ms`, after the table's rounding row).

Only the first difference of a trace is reported: `oracle-divergence` with `trace`, `step` (0 is the `cfg` line), `line`, `byte` and
`what` (`cfg`, `in`, `fx`, `vw` or `steps`). `line` is the 1-based line of the Rust trace file and `byte` the 0-based offset in that
line, as `trace_first_diff` gives them: the position of the first differing byte; where one text ends inside the other, the position
where the shorter one ends (`what = fx` for an `fx` line the replayer lacks, `steps` for a missing or extra step: the line of the first
step the replayer lacks, or the line after the Rust trace). The replayer's own output is never put in a finding.

## The gate files (`products/<p>/`, gate-owned, hashed into the verdict)

`oracle-policy.toml`:

```
required = true                         # the product must be graded with --oracle (else `oracle-bundle-missing`); default false
replayer = "//apps/lockers/lkapp/sim:oracle_replay"
traces = ["scripted-01", ...]           # ids the bundle must hold (`oracle-bundle-missing` per missing id); default none
excluded_max = 0                        # the ratchet's ceiling (below); default 0
```

`oracle-normalise.toml`: **empty by default.** Rows (`[[row]]`) need `id`, `kind`, `decision` (a decision id) and `reason`, and the keys of
their kind: `drop-field` (`field`: removed at any depth of `vw.s` and of the `fx` lines; e.g. the audit `at`), `round-field` (`field`, `to`:
an integer is rounded up to a multiple of `to`; e.g. the 250 ms tick quantisation), `drop-fx` (`port`: the `fx` lines of that port). A row
is never added to make a trace pass without an entry in the product's `docs/decisions.md` (D8: Rust wins unless the decision says
otherwise); rows may be removed without sign-off, never added. The product's words about it are never read.

`oracle-excluded.toml`: Rust outcomes with no honest C injection, `[[exclude]]` tables of `trace_id`, `reason`, `decision`. A ratchet: the
number of entries may not exceed `excluded_max` of the policy (`oracle-excluded-grew`), so growing it takes a change to two gate files,
which only a task whose contract names that loosening may make (`docs/trust.md`). An excluded trace is not replayed (the package does not hold it), does not count
for `oracle-count-short`, and must be in the bundle (a ghost entry is exit 2).

## Findings

| rule | when |
|---|---|
| `oracle-divergence` | a replay differs from its Rust trace (`trace`, `step`, `line`, `byte`, `what`) |
| `oracle-no-settle` | an `ns` record: the replayer's step did not settle (`trace`, `step`) |
| `oracle-bundle-missing` | the policy lists a trace id the bundle lacks (`trace`), or the policy requires a bundle and there is none (`reason`) |
| `oracle-count-short` | fewer traces replayed than the bundle holds, the excluded ones left out (`expected`, `replayed`) |
| `oracle-excluded-grew` | more exclusions than `excluded_max` (`excluded`, `max`) |
| `oracle-replay-failed` | (grade only) the replayer did not build or failed on a trace |

Exit 2 (never a pass): any malformed bundle, trace, results directory (a file that is not `<id>.trace` of a replayed trace of the bundle,
a symlink), table, exclusion list or policy; an excluded trace that was replayed or that the bundle lacks.

## Fixture and canaries

`selftest/sim/oracle/` has `gen_traces.py` (the Rust side of a toy pad kiosk: writes the fixture bundle), `replay.c` (its C replayer,
stdin to stdout) and `BUCK`. `selftest/sim.sh` builds the replayer, replays the fixture bundle with zero divergence, flips one byte of a
trace and checks `oracle-divergence` at that line and byte, and runs a replayer with a deliberate bug. The canaries `oracle-green`
(control), `oracle-divergence` (a replayer that forgets to clear the pad on `cancel`) and `oracle-bundle-missing` (the policy lists a
trace the bundle does not hold) grade a product with that replayer end to end.
