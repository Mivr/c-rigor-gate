# Registered products

Each product has a gate-owned directory `products/<name>/` (`product.toml`, `policy.toml`, `expected-tests.json`,
`tasks/`). Products never edit it; see [grade.md](grade.md) and [product-checks.md](product-checks.md).

| Product | Repo | Layout `include` | Notes |
|---|---|---|---|
| `annas-c` | `Mivr/annas-c` | `core/**`, `json/**`, `url/**`, ... (14 module directories) | The model product; policy is the standard deny list. |
| `business-apps` | `Mivr/business-apps` (private monorepo, cell `biz`) | `lib/**` | Add `apps/**` when the first app module lands (a pattern that matches nothing is `stale-include`). `main` holds `lib/base/core` only (131 tests), moved from annas-c `core`. |

## G25: the allocation deny list (P002)
`business-apps` adds, to annas-c's standard `[global]` deny list, every way to get memory outside a caller-supplied arena
or static storage. A reference to one of them in a graded module is a `symbols` FAIL (`denied-symbol`) unless that
module lists it in `allow` or is a trusted gate module (`gate//ctest:ctest`):

`malloc`, `calloc`, `realloc`, `free`, `aligned_alloc`, `posix_memalign`, `memalign`, `valloc`, `pvalloc`,
`reallocarray`, `strdup`, `strndup`, `asprintf`, `vasprintf`, `getline`, `getdelim`, `open_memstream`, `mmap`,
`munmap`, `mremap`, `brk`, `sbrk`.

Canaries `alloc-deny` (malloc and free) and `alloc-deny-strdup` keep it red.
