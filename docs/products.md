# Registered products

Each product has a gate-owned directory `products/<name>/` (`product.toml`, `policy.toml`, `expected-tests.json`,
`tasks/`; optional `architecture.toml`, [layering.md](layering.md), and `decoupling.toml` with its
`decoupling-baseline.toml`, [decoupling.md](decoupling.md)). Products never edit it; see [grade.md](grade.md) and [product-checks.md](product-checks.md).

| Product | Repo | Layout `include` | Notes |
|---|---|---|---|
| `annas-c` | `Mivr/annas-c` | `core/**`, `json/**`, `url/**`, ... (14 module directories) | The model product; policy is the standard deny list. |
| `business-apps` | `Mivr/business-apps` (private monorepo, cell `biz`) | `lib/**` | Add `apps/**` when the first app module lands (a pattern that matches nothing is `stale-include`). `main` holds `lib/base/core` only (131 tests), moved from annas-c `core`. |

## `c_library` parameters and `exported_deps` (T110)
`c_library(name, srcs, headers, deps, exported_deps, visibility, system_libs)`. `deps` are private: their headers are not
visible to the library's dependents. `exported_deps` (a literal list of labels, `c_library` only) are passed to the cxx
library as exported deps, so their headers and link inputs reach every dependent transitively. For every gate check
(facts, layering/architecture edges, fan-out counts, the mutants package, the witness scope) they are deps of THIS library:
the edge is `B -> C`, it must be allowed for B exactly as a plain dep is, and a dependent `A -> B` gains no edge to `C`.
If A's own sources use `C` (call its symbols), the `symbols` gate still reports `undeclared-symbol` unless A lists `C`
directly in `deps`: the gate checks symbols against the DIRECT deps' exports, never against what a header makes visible,
and that is unchanged. A label in both `deps` and `exported_deps` fails the package load with a clear message. `rigor buckfiles` accepts
`exported_deps` on `c_library` only, checked like `deps`.

**When to export.** Export exactly the libraries whose headers the library's PUBLIC headers include. Never export for
convenience, to save a dependent a line, or because the library's `.c` files use it (that is a private `deps` entry).

## Linking a sysroot library (T095)
A module that needs libpthread (business-apps `lib/io/osal`, the only module allowed to call pthread) declares it on its
library, and the product policy repeats it in that module's table (the gate's cross-check; both directions are errors):

```python
c_library(name = "osal", srcs = ["osal.c"], headers = ["osal.h"], system_libs = ["pthread"])
```
```toml
[module."//lib/io/osal:osal"]
system_libs = ["pthread"]
allow = ["pthread_create", "pthread_join"]    # the symbols it references are still checked as usual
```
`system_libs` is an allow-list of bare sysroot library names in `rules/c.bzl`: `pthread` (no link flag in the Android mode), `android` and `log` (T-G1: `-landroid`, `-llog`, Android mode only), and `X11` (T117: libX11 and its
link-time closure, [product-checks.md](product-checks.md#system-libraries-t095)); a new entry needs a product that needs it. It becomes the exported post-link flag `-lpthread`, resolved in the pinned sysroot by the toolchain's own link
line (never a host path), so every binary, test and mutant binary that links the library gets it; `c_mutants` reads the
flags from the library's link info (the module and its `deps`) and puts them after the objects and archives of its raw
links. The facts record `system_libs` per module. Details and findings: [product-checks.md](product-checks.md#system-libraries-t095).
Self-test: the last steps of `selftest/mutate.sh` (a real pthread in release and san, a binary, and the mutants of two modules).

## `c_android_so`: a shared object for Android (T-G2)
`c_android_so(name, exports, srcs, deps, system_libs, visibility)` links `lib<name>.so` for the `android` mode only
(`--target-platforms toolchains//:android_release`; every other mode reports it incompatible, and `c_binary` and `c_test`
are incompatible with the android mode). `exports` is the exact list of dynamic symbols: a generated GNU version script
makes them global and everything else local, `--no-undefined`, `relro`/`now` and `--gc-sections` are fixed, the flags are
the release list itself (`_RELEASE_COMPILE`), and the link is 16 KB page aligned. The output is checked by
`rules/elf_check.py` before it is published as the target's output: ELF64 AArch64 shared object with the standard header
sizes, every `PT_LOAD` segment aligned to a power of two that is a multiple of 16384 with offset and vaddr congruent, a real
string table, and a dynamic symbol table that defines exactly `exports` (no more, none missing, none twice). Nothing may
`deps` on a `c_android_so` or on what it derives (`<name>_facts`, `<name>__lib`, `<name>__map`): `buckfiles` refuses it.

**What `rigor grade` does with it** (`grade_checks._android_facts`): `<name>_facts` (kind `c_android_so`, rule
`c_android_facts`, which a `kind(c_facts, //...)` Linux query never selects) is built for `toolchains//:android_release`
together with the `android_so` output itself and `toolchains//:libc_symbols_android`. A `c_android_so` without its facts
target, or any build failure there, makes the fact gates NOT_RUN, which fails the verdict. The facts then go through the
same gates as every module, in the one directory: `semantic-suppressions`, `symbols` (the NDK export list is the reserved
list for the Android kinds, `facts_symbols.run(libc_android=...)`), `layering`, `decoupling` (kind judged: declared deps =
used deps) and `structure` (structure targets for the module are built in the android mode, `c_android_structure`, NDK
clang and roots). Canaries `android-so-denied-symbol` (a `getenv` call) and `android-so-inline-asm` fail the grade.

**What it does NOT grade (condition for T-A2)**: the facts cover the `.so`'s own `srcs` as the NDK compiles them. The
libraries in its dependency closure are graded from their Linux release facts only, so code under `#ifdef __ANDROID__`,
`__BIONIC__` or `__aarch64__` in a closure library is compiled for Android but never scanned, and no check compares the
release and android compiles of a library (no android `mode-divergence`). T-A2 must add an android facts twin per
library of that closure (a distinct facts label, selected by the closure of the `android_so` targets) and that comparison
before a product ships a closure that contains such code; until then a product must keep platform-conditional code in
the `c_android_so`'s own sources. Example: `examples/android`. Self-test: `selftest/android.sh`; unit tests:
`gate/tests/test_elf_check.py`, `gate/tests/test_grade_android.py`.

## G25: the allocation deny list (P002)
`business-apps` adds, to annas-c's standard `[global]` deny list, every way to get memory outside a caller-supplied arena
or static storage. A reference to one of them in a graded module is a `symbols` FAIL (`denied-symbol`) unless that
module lists it in `allow` or is a trusted gate module (`gate//ctest:ctest`):

`malloc`, `calloc`, `realloc`, `free`, `aligned_alloc`, `posix_memalign`, `memalign`, `valloc`, `pvalloc`,
`reallocarray`, `strdup`, `strndup`, `asprintf`, `vasprintf`, `getline`, `getdelim`, `open_memstream`, `mmap`,
`munmap`, `mremap`, `brk`, `sbrk`.

Canaries `alloc-deny` (malloc and free) and `alloc-deny-strdup` keep it red.
