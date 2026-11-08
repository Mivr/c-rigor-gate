# Registered products

Each product has a gate-owned directory `products/<name>/` (`product.toml`, `policy.toml`, `expected-tests.json`,
`tasks/`). Products never edit it; see [grade.md](grade.md) and [product-checks.md](product-checks.md).

| Product | Repo | Layout `include` | Notes |
|---|---|---|---|
| `annas-c` | `Mivr/annas-c` | `core/**`, `json/**`, `url/**`, ... (14 module directories) | The model product; policy is the standard deny list. |
| `business-apps` | `Mivr/business-apps` (private monorepo, cell `biz`) | `lib/**` | Add `apps/**` when the first app module lands (a pattern that matches nothing is `stale-include`). `main` holds `lib/base/core` only (131 tests), moved from annas-c `core`. |

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
`system_libs` is an allow-list of bare sysroot library names in `rules/c.bzl`: `pthread` only until a product needs
another. It becomes the exported post-link flag `-lpthread`, resolved in the pinned sysroot by the toolchain's own link
line (never a host path), so every binary, test and mutant binary that links the library gets it; `c_mutants` reads the
flags from the library's link info (the module and its `deps`) and puts them after the objects and archives of its raw
links. The facts record `system_libs` per module. Details and findings: [product-checks.md](product-checks.md#system-libraries-t095).
Self-test: the last steps of `selftest/mutate.sh` (a real pthread in release and san, a binary, and the mutants of two modules).

## G25: the allocation deny list (P002)
`business-apps` adds, to annas-c's standard `[global]` deny list, every way to get memory outside a caller-supplied arena
or static storage. A reference to one of them in a graded module is a `symbols` FAIL (`denied-symbol`) unless that
module lists it in `allow` or is a trusted gate module (`gate//ctest:ctest`):

`malloc`, `calloc`, `realloc`, `free`, `aligned_alloc`, `posix_memalign`, `memalign`, `valloc`, `pvalloc`,
`reallocarray`, `strdup`, `strndup`, `asprintf`, `vasprintf`, `getline`, `getdelim`, `open_memstream`, `mmap`,
`munmap`, `mremap`, `brk`, `sbrk`.

Canaries `alloc-deny` (malloc and free) and `alloc-deny-strdup` keep it red.
