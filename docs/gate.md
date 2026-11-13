# rigor: the gate decision kernel

`gate/rigor` is a small Python 3.12 (standard library only) program that decides pass/fail.
Everything fails closed. Run its tests with `selftest/gate.sh`.

## Exit codes and result files
| Exit | Meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL |
| 2 | internal error (unreadable input, unknown field, tool failure, any exception). Counts as FAIL. |

Each gate subcommand takes `--out FILE` and writes
`{"gate": id, "status": "PASS"|"FAIL", "findings": [...], "metadata": {...}}` as canonical JSON
(sorted keys, compact separators, trailing newline). Findings carry `rule`, `severity`
(`error` or `info`) and rule specific fields; they are sorted and byte-identical on rerun. Anything
volatile (shas of the run, counts, error text) lives only in `metadata`. A result is `FAIL` if
any finding has severity `error`; `info` findings never fail a gate.

On exit 2 with `--out`, the file is replaced by a `FAIL` result with the single finding
`internal-error` (the error text goes in `metadata.error`), so a stale `PASS` can never survive.
`verdict` removes its stale `--out` file instead.

Git is run with no user or system config, `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE=/dev/null`
(so `refs/replace/*` and `info/grafts` in the agent's repo cannot rewrite the trees or ancestry
being judged), `-c core.fsmonitor=false -c core.hooksPath=/dev/null`, `--no-ext-diff --no-textconv`, `--ignore-submodules=none`,
`--literal-pathspecs`, and `-z` output, and paths are handled as raw bytes. The graded repository
must be a clone assembled by the gate driver; its own config is not a trusted input.

## Subcommands
### `contract --repo R --base B --head H --contract T.toml [--out F]`
Contract keys: `id` (string), `allowed` (globs, required), `protected` (globs, wins over allowed),
`max_files` (non-negative integer). Unknown keys, wrong types and bad globs are exit 2.
Checked: every path in `git diff merge-base(B,H)..H` (renames are two paths: old and new).
Rules: `outside-allowed`, `protected`, `symlink` (any symlink added, changed or removed),
`submodule` (any gitlink), `unsupported-mode`, `bad-path` (`..`, empty or absolute),
`too-many-files`, `approval-in-repo`.

Globs are relative POSIX paths. `*` matches within one segment. `**` must be a whole segment: in
front or in the middle it matches zero or more directories, at the end it matches one or more
path segments. Every other character is literal (no `?`, no `[...]`). Matching is case sensitive.

### `suppressions --repo R --base B --head H [--approvals DIR] [--allowed-signers F] [--out F]`
Scans every **added** line (zero-context patch, files forced to text so attributes cannot hide
them) of every non-deleted changed path against the table in `gate/rigor_lib/patterns.py`; that
file is the only place patterns live. Rules: `forbidden-pattern` (path, line, pattern id),
`binary-artifact` (added or changed `*.o *.a *.so *.profdata *.profraw`, anywhere in the repo),
plus `approval-in-repo` and `forged-approval`.
An approval of kind `suppression` and scope `<path>:<line>-<pattern id>` covers one violation.

### `tests --results DIR --expected E.json [--previous P.json] [--approvals DIR --repo R --head H]`
Results are `*.jsonl` files in DIR (not recursive): one `{"id","status","asserts"}` object (plus an optional `reason` string of at most 1024
characters) per test and one final `{"summary":{"total","passed"}}` per file. `E.json` and `P.json` are
`{"ids": ["suite/name", ...]}` (gate-owned input; a defect is exit 2). Ids match
`[A-Za-z0-9_.+:-]+/[A-Za-z0-9_.+:-]+`.
Rules: `missing-test`, `duplicate-test`, `test-not-pass`, `no-assertions`,
`unexpected-failing-test`, `malformed-line` (with `reason`), `missing-summary`,
`summary-mismatch`, `no-results`, `expected-empty`, `test-removed` (id in `--previous` but not in
`--expected`; covered by a `test-removal` approval whose scope is the test id), and the
informational `unexpected-test`.

### `ratchet --old O.toml --new N.toml --spec S.toml [--approvals DIR --repo R --head H]`
Old and new are flat TOML: a number or a list of strings per key. The spec has one table per key
with `direction = "down" | "up" | "shrink"`. Rules: `ratchet-regressed`, `missing-key`,
`unspecified-key` (key in new but not in spec), `bad-value`; `new-key` (no baseline yet) is
informational. An approval of kind `ratchet` and scope `<file name of --new>:<key>` covers a
`ratchet-regressed` finding only.

### `verdict --order O.txt --results DIR --out verdict.json`
`O.txt` lists gate ids (one per line, `[a-z0-9][a-z0-9_.-]*`). The result of gate `X` is
`DIR/X.json`; absent means `NOT_RUN`. Overall `PASS` needs a non-empty list with every gate
`PASS`. A result file that is malformed, names another gate, or whose status disagrees with its
findings is exit 2. Output: `{"core": {...}, "core_sha256": ..., "metadata": {...}}`. `core`
holds, per gate, id, status, findings count and the sha256 of its canonical findings, so the
hash commits to the findings. `metadata` (gate metadata, paths, unlisted result files) is not
hashed.

### `approve --kind K --scope S --reason TEXT --repo-sha SHA --key KEYFILE --out DIR`
Writes `DIR/<sha256>.json` (canonical JSON of kind, scope, reason, repo_sha; named by the hash of
its bytes) and `DIR/<sha256>.json.sig` made with `ssh-keygen -Y sign -n c-rigor-gate`.

## Approvals
Kinds: `suppression`, `test-removal`, `ratchet`. Approvals live in a directory outside the
product repo (`--approvals`); `--allowed-signers` defaults to `gate/allowed_signers`, which the
owner fills with `<principal> namespaces="c-rigor-gate" <public key>` lines. The driver must never
point `--allowed-signers` or `--approvals` at anything the product controls.

An approval counts only if all hold: the file name is the sha256 of its bytes; its signature
verifies (`ssh-keygen -Y find-principals` then `-Y verify`, namespace `c-rigor-gate`) against
`allowed_signers`; the JSON has exactly the four keys with valid values; `repo_sha` exists and is an
ancestor of (or equal to) the graded head; and kind and scope match exactly.

Anything else in the approvals directory (unsigned, badly signed, wrong namespace or signer,
tampered, malformed, orphan signature, stray file) is a `forged-approval` error finding (with a
`reason`), whether or not it was needed. An approval that is validly signed but for a commit that
is not an ancestor is simply not applicable, and the violation it was meant to cover still fails.
A file named like an approval (`<64 hex>.json` or `.json.sig`) anywhere in the graded tree is an
`approval-in-repo` finding.
Gates that take `--approvals` need `--repo` and `--head` (for the ancestry check); the run is exit 2
without them. Existence of ssh-keygen is only required when the approvals directory is non-empty.

### Signer roles (`gate/signer_roles.toml`, T132)
`[principal.<name>] kinds = [...]` lists the approval kinds a signer may sign; the name is the principal of
`allowed_signers` as `ssh-keygen -Y find-principals` reports it. With `--signer-roles FILE` an approval counts only
if its signer's principal is listed with the approval's kind; otherwise it is a `forged-approval` finding with
reason `kind-not-allowed-for-signer`. A principal in `allowed_signers` that the file does not list may sign nothing.
The shipped file gives `orchestrator` the five kinds that exist (`suppression`, `test-removal`, `ratchet`,
`equivalent-mutant`, `witness-equivalent-mutant`), so it reproduces today's rule. **The flag is off by default and no
gate passes it yet** (a later task wires it); `approvals.load_approvals(..., roles_path=None, ledger=None)` is the
library surface. `--ledger DIR` likewise switches on the tighten-only rule of `docs/trust.md`
(reason `tighten-only`). Both are accepted wherever `--approvals` is.

### `ledger append|verify|claims`
`ledger append --ledger DIR --kind K --subject S [--evidence FILE] --at N`, `ledger verify --ledger DIR [--head SHA]`
(prints the head; exit 1 if the chain is broken), `ledger claims --ledger DIR`. See `docs/trust.md`.

## Known limits
- Pattern scanning is a line regex. Line splices (a backslash-newline inside a token) and macro
  token-pasting still evade it. A semantic scan over the preprocessed source and the object
  symbols is planned for a later task; do not try to solve that with more regexes.
- `symlink` and `submodule` changes are refused outright rather than judged by target.
- Scope strings for `suppression` approvals pin a line number, so they go stale when lines move.

## Hygiene: why `-B` and `PYTHONDONTWRITEBYTECODE`
Python would otherwise write `__pycache__/*.pyc` next to the sources, which dirties the worktree
(and the contract gate would see the files) and lets a stale compiled module outlive its source.
`selftest/gate.sh` runs `python3 -I -B`, and `gate/rigor` sets `sys.dont_write_bytecode` before any
import. `-I` ignores `PYTHON*` variables, so the `-B` flag (not `PYTHONDONTWRITEBYTECODE`) is what
works under isolated mode; the test helper also launches `rigor` with `-I -B`. Nothing here
depends on `.gitignore`.

## Running the tests
`selftest/gate.sh` runs the unit tests through `gate/tests/run_parallel.py`: the same discovery as
`unittest discover -s gate/tests -t gate`, but each test module runs in its own subprocess with its own
`TMPDIR`, `--jobs` at a time (default: twice the effective CPUs, from the cgroup `cpu.max` quota and affinity, clamped to 2..16; `--timeout` kills a hung module after 900 s).
It prints one line per module, the full output of failed modules, and `Ran N tests in S s`. It exits 1 on any
failure, import error, missing test count, or when tests run differs from tests discovered, and 2 on a runner
error. Module durations are kept in `$TMPDIR/gate-test-durations.json` to start the longest modules first (a
scheduling hint only). `GATE_SERIAL=1 selftest/gate.sh` runs the old single-process command.
