# T002: gate driver kernel (`rigor`)

Repo: `Mivr/c-rigor-gate`. Branch `task/T002`. Read `AGENTS.md` and `plan/phase1.md` first.
T001 (toolchain) runs in parallel in another worktree; do not touch its paths.

## Goal
The trust kernel: a small, boring, fully tested Python 3.12 **stdlib-only** program that decides pass/fail.
Everything here fails closed. The orchestrator will review every line, so prefer obvious code over clever code.

## Allowed paths
`gate/**`, `selftest/gate.sh`, `docs/gate.md`. Nothing else.

## Entry point
`gate/rigor` (executable, `#!/usr/bin/env -S python3 -I`), package `gate/rigor_lib/`. Every subcommand exits
**0 = PASS, 1 = FAIL, 2 = internal error**. Any uncaught exception, unreadable input, unknown field, or tool
failure is exit 2 and counts as FAIL. Each subcommand can also write a gate result JSON (`--out <file>`):
`{"gate": "<id>", "status": "PASS"|"FAIL", "findings": [ {..sorted, deterministic..} ], "metadata": {...}}`.
Findings and their order must be byte-identical on rerun; timings, paths of temp dirs and hostnames go only in
`metadata`.

## Subcommands
1. **`contract`** `--repo R --base B --head H --contract T.toml`
   Contract TOML (`tomllib`): `id`, `allowed = [globs]`, `protected = [globs]` (optional, wins over allowed),
   `max_files` (optional). FAIL if any path changed between merge-base(B,H) and H (added, modified, deleted,
   renamed: **both** old and new names; mode changes; symlinks; submodule changes) is outside `allowed` or inside
   `protected`. Globs: `**` = any depth, `*` = within one segment; matching is on POSIX paths, no `..`. Paths are
   read with `git diff -z --name-status --no-renames` style parsing so odd filenames (spaces, newlines,
   non-UTF-8) cannot smuggle a path past the check. Unknown contract keys: exit 2.
2. **`suppressions`** `--repo R --base B --head H [--approvals DIR]`
   FAIL on any **added** line (in any file type) matching a forbidden pattern, unless covered by a valid approval
   (see 4). Patterns, case-sensitive unless noted, in one table in the code:
   `#\s*pragma\s+(clang|GCC)\s+(diagnostic|optimize|system_header)`, `_Pragma\s*\(`, `NOLINT`,
   `-Wno-`, `-w\b` (as a flag), `no_sanitize`, `__attribute__\s*\(\(\s*(optnone|no_instrument_function)`,
   `#\s*(define|undef)\s+(assert|NDEBUG)\b`, `__SANITIZE_ADDRESS__`, `__has_feature\s*\(\s*\w*sanitizer`,
   `getenv\s*\(\s*"(CI|GATE|RIGOR|BUCK|TEST)`, `LLVM_PROFILE|__llvm_profile`, `LLVMFuzzer` outside files
   named `*_fuzz.c`, `-fno-sanitize`, `UBSAN_OPTIONS|ASAN_OPTIONS|LSAN_OPTIONS`.
   Report file, line number, pattern id. Also FAIL if a file is added with a binary or generated-looking name
   under a source dir (`*.o *.a *.so *.profdata *.profraw`).
3. **`tests`** `--results DIR --expected E.json [--previous P.json] [--approvals DIR]`
   Result format (the `ctest` framework, built later, will emit it): JSON Lines files `*.jsonl` in DIR, one
   object per test: `{"id": "<suite>/<name>", "status": "pass"|"fail"|"skip", "asserts": <int>}` and one final
   `{"summary": {"total": n, "passed": n}}` per file. FAIL if: any expected id is missing, duplicated, not
   `pass`, or has `asserts < 1`; any file lacks a summary or the summary disagrees with its lines; any line is
   malformed; the directory is empty. With `--previous`: the expected set may only grow (removed ids FAIL unless
   approved). New ids not in expected are reported as findings `unexpected-test` (informational, not FAIL).
4. **Approvals (signed sign-offs)**
   `rigor approve --kind K --scope S --reason TEXT --repo-sha SHA --key KEYFILE --out DIR` writes
   `<DIR>/<sha256>.json` plus `.sig` made with `ssh-keygen -Y sign -n c-rigor-gate`. Verification uses
   `ssh-keygen -Y verify` against `gate/allowed_signers` (a file in this repo; for tests use a throwaway key
   generated into a temp dir). Kinds: `suppression` (scope = `path:line-pattern-id`), `test-removal`
   (scope = test id), `ratchet` (scope = `file:key`). An approval is valid only for the exact scope and only
   when `repo-sha` is an ancestor of the head being graded. An unsigned, badly signed, wrong-namespace,
   wrong-signer or malformed approval is not just ignored: it is a FAIL finding `forged-approval`.
   Approvals never live in the product repo; a file named like an approval inside the graded repo is a FAIL.
5. **`ratchet`** `--old O.toml --new N.toml --spec S.toml [--approvals DIR]`
   Spec gives, per key, `direction = "down"|"up"` (numbers) or `"shrink"` (sets of strings). FAIL on any key that
   moved the wrong way without an approval, on keys missing from new, and on keys in new not in spec.
6. **`verdict`** `--order O.txt --results DIR --out verdict.json`
   O.txt lists gate ids in fixed order. Status per gate is the result file's status, or `NOT_RUN` if absent.
   Overall `PASS` only if the list is non-empty and every gate is `PASS`. Canonical JSON (sorted keys,
   `separators=(",", ":")`, trailing newline) so the deterministic core hashes identically on rerun; put
   metadata in a separate `metadata` object excluded from `core_sha256`, which the verdict also records.

## Tests
- `gate/tests/` with `unittest`, run by `selftest/gate.sh` (`python3 -I -m unittest discover`). Tests build
  tiny git repos in temp dirs; no network; no dependency on the host's git config (set `GIT_CONFIG_GLOBAL` and
  `GIT_CONFIG_NOSYSTEM` in the test env).
- **Every rule needs a test that turns it red and one that keeps it green**, including each suppression
  pattern, each contract escape (rename out of allowed, delete of a protected file, path with newline,
  symlink pointing into protected, submodule), and each forged-approval variant.
- Determinism test: run `verdict` twice on the same inputs; `core_sha256` must be equal.
- Fail-closed tests: corrupt inputs, missing git, missing `ssh-keygen` (simulate via `PATH`), unknown keys.
  All must give exit 2, never 0.

## Acceptance (the orchestrator re-runs)
```sh
selftest/gate.sh                       # all tests pass, prints the count
gate/rigor contract --help && gate/rigor verdict --help
```
Report the number of tests per subcommand, the full list of red/green cases covered, and any rule you
could not implement exactly as written (with why).
