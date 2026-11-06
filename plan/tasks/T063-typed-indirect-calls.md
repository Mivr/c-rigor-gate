# T063: resolve indirect calls by function type in `indirect-cycle-possible` (sound, fail closed)

Repo: `Mivr/c-rigor-gate`. Branch `task/T063`. Read `AGENTS.md` ("Working efficiently"), `docs/structure.md` (all of
it, especially the `indirect-cycle-possible` row and "Known limits"), and `gate/rigor_lib/structure_scan.py`
and `structure.py`.

## Problem (A041, 2026-11-07)
annas-c is a ports-and-adapters design. Every port is an ops table of function pointers, and every adapter's table
functions eventually call another injected port (for example, `wire` lazyfs `lz_write` → `p.ops->write`; posix_fs
`pfs_op_write` → `fs->sys->pwrite`). Today's rule fires whenever **any** address-taken function F reaches **any**
call through a value G. So 22 non-test findings in `wire`, `posix_fs`, `app`, `annas`, `posix_clock` and
`tls_stream` cannot be fixed without hiding calls. The rule is sound but carries no type information. A call
through a value of type `ports_fs_err_t (*)(void *, ports_fs_file_t, const void *, size_t)` cannot reach a
function of type `bool (*)(void *, core_str_t, core_str_t *)` unless the program converts between those
pointer types.

## Requirement: type-based targets, sound under C's rules, fail closed
1. **Facts.** For each call through a value, record the callee's canonical function type: clang's
   `desugaredQualType` of the pointee, with parameter names dropped and typedefs resolved. For each
   address-taken function, record its canonical type. Also record every **function-pointer conversion**: a
   cast, implicit or explicit, that changes a function-pointer type, or converts between a function pointer and
   `void *` or an integer. Also record every **union or memcpy/byte copy whose type has a function-pointer
   member**, if one is detectable. If one is not, say so in "Known limits".
2. **Edges.** A call site G of type T may reach an address-taken function F only if F's canonical type is
   compatible with T, under C11 6.7.6.3 compatibility (identical after canonicalisation, with `void f()`
   unprototyped matching any). Compute the cycle check on these typed edges.
3. **Fail closed.** If the product converts any function pointer between incompatible types or to or from a
   non-function type, or uses a variadic or unprototyped function-pointer type at a call site, then every call
   site of a type involved in that conversion falls back to today's untyped rule. If the facts cannot tell,
   fall back too. Report the fallback as info `indirect-untyped-fallback`, with the site, so it is visible.
4. **Callbacks into code the product does not define** (`qsort(.., cmp)`, `fp_args`) keep today's rule.
5. **Red tests first**, as unit tests over small JSON fact fixtures and over C fixtures built through the
   existing structure selftest:
   - the annas-c shape (two ops tables of different types, one calling the other) is now green;
   - a real cycle through a dispatch table of one type (F in the table calls the dispatcher of the same type)
     stays red;
   - the same cycle hidden by casting F to the other table's type through `void *` is red, either through the
     fallback or directly;
   - a cycle through an unprototyped pointer is red;
   - a `qsort` callback cycle is red as today.
6. **Canary:** `structure-typed-cycle-cast` is a cycle hidden by a function-pointer cast. Expected: `structure`
   FAIL with `indirect-cycle-possible`. Every existing structure canary stays exactly as it is.
7. **annas-c count:** run the structure facts and `rigor structure` over annas-c main (clone
   `/var/tmp/src/annas-c` into your cache dir; read-only source) before and after. Report every remaining
   finding with its chain, and say whether each is real.

## Allowed paths
`gate/rigor_lib/structure*.py`, `gate/rigor_lib/grade_structure.py`, `rules/structure.bzl`,
`gate/tests/test_structure*.py`, `selftest/structure.sh` and its fixtures, a new
`canaries/structure-typed-cycle-cast/`, and `docs/structure.md`.
**In flight in parallel:** T061 and T062 (`trajectory*`), and T039 (`grade_pipeline.py`, `grade_tree.py`,
`grade_steps.py`, `grade_policy.py`, `grade_mutants.py`, `witness*`). Touch none of their files. Do not edit
`plan/backlog.md` or `plan/backlog.d/`.

## Acceptance
```sh
python3 -I -B -m unittest discover -s gate/tests -t gate -p 'test_structure*.py'
selftest/structure.sh
selftest/gate.sh
TMPDIR=/var/tmp/cache/T063/tmp selftest/canaries.sh --only structure-typed-cycle-cast --only structure-recursion
```
(Use `tools/job` for anything over 2 minutes.) Report the type canonicalisation you chose, the fallback
conditions, the annas-c before and after numbers, and every deviation. This is a soundness change, so state in the
report why no real cycle can pass.
