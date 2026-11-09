# Profiles, floors and the technique matrix (T127, P003 section 4 and 10.1)

A module's **profile** says what kind of code it is; the **level** (L1-L5) says how much of each technique. In v1 a
level only tunes mutation. Nobody signs a profile or a level: the gate computes a **floor** from facts it already has,
and a policy may only add. This task is the pure library (`gate/rigor_lib/profiles.py`) and one judge,
`rigor policy-check` (`gate/rigor_lib/policy_check.py`). **No gate of `rigor grade` uses either yet**, and no product
policy has a `profile` key yet.

## The policy key
```toml
[module."//pkg:name"]
level = "L3"
profile = ["pure", "parser"]     # a list of names; a single string ("pure") is accepted too
```
Every reader of `policy.toml` accepts the key and ignores it (`facts_policy` lists it among the allowed keys; the
others read only the keys they know), so a gate behaves the same with or without it. Only `policy-check` reads it. A
value that is neither a string nor a list of strings, or a list with a duplicate, is exit 2.

## The profiles
`pure` (domain rules, containers, encoders: no IO, no threads), `parser` (reads bytes it did not write), `adapter`
(thin code over a syscall or a third-party library), `concurrent` (shared between threads), `wiring` (composition:
tables, roots, effect dispatch), `ui` (layout and text), `safety` (failure moves hardware). A module may carry several;
it then gets the union of their techniques.

## The technique matrix
`●` gates the verdict, `○` is reported, blank is not run; `L3+` means from that level up. `profiles.MATRIX` is this
table as data and `profiles.required(profiles, level)` returns `{technique: "gate" | "report"}`: the union over the
profiles, `gate` winning over `report`, a step applying from its level up. Qualifiers the P003 table prints (`if it
parses`, `decoders`, `driver`, `round trip`, `where declared`, `per operation`, the MC/DC threshold) narrow what a
technique is applied to, not whether it runs; they are in `profiles.QUALIFIERS` and `required` ignores them.

| Technique | `pure` | `parser` | `adapter` | `concurrent` | `wiring` | `ui` | `safety` |
|---|---|---|---|---|---|---|---|
| `tests_release_san` | ● | ● | ● | ● | ● | ● | ● |
| `msan` | ● | ● | ○ | ○ |  |  | ● |
| `tsan` |  |  |  | ● | ● |  |  |
| `mutation_zero_survivors` | ● L3+ | ● L3+ | ○ | ○ |  |  | ● |
| `pseudo_tested_zero` | ● L2+ | ● L2+ | ● L2+ | ● | ● | ● | ● |
| `model_or_property` | ● L3+ | ● |  |  |  |  | ● |
| `fuzz` |  | ● | ● |  |  |  | ● |
| `fault_injection_sweep` |  |  | ● |  |  |  | ● |
| `real_os_tests` |  |  | ● | ● |  |  |  |
| `cproof_no_ub` |  | ○ L3+, ● L4 |  |  |  |  | ● |
| `cproof_safety_properties` |  |  |  |  |  |  | ● |
| `mcdc` |  |  |  |  |  |  | ● L4 |
| `whole_app_simulation` |  |  |  |  | ● | ● | ● |
| `oracle_trace_replay` |  |  |  |  | ● | ● |  |
| `catalogue_and_layout` |  |  |  |  |  | ● |  |
| `perf_class` | ● | ● | ● |  |  |  | ● |
| `structure_caps` | ○ | ○ | ○ | ○ | ○ | ○ | ● L4 |

Two readings of the P003 table, both literal: `structure_caps` for `safety` is blank below L4 (the cell says `● L4`),
and `cproof_no_ub` for `parser` reports at L3 and gates from L4, nothing below L3.

## The floors (`profiles.profile_floor`)
`profile_floor(facts, structure=None, prefixes=(), third_labels=())` returns the set of profiles the facts force, or
`{"pure"}` when no rule applies; `floor_reasons` returns, per profile, the `(rule id, symbol or function)` pairs that
triggered it. `ui` and `safety` are never floors: they are declared only. A declared `pure` is never required either:
the floor `pure` only means "nothing forces more".

| Rule | Profile | Triggers |
|---|---|---|
| `F-adapter` | `adapter` | an undefined symbol of the syscall and IO table below, an undefined symbol that starts with a reserved prefix of a gate-owned third-party library (`third_party/RESERVED_PREFIXES`), or a dep on such a library (`ALLOWED_LABELS`) |
| `F-concurrent` | `concurrent` | an undefined `pthread_*`, `thrd_*`, `mtx_*`, `cnd_*` symbol; an `__atomic_*`, `__sync_*` or `__c11_atomic_*` identifier in the semantic facts (the builtins, which leave no symbol) |
| `F-parser` | `parser` | an exported function (its name is a defined symbol of the module) with a parameter of type pointer to `char`, `unsigned char`/`uint8_t`, `signed char` or `void`, directly followed by an integer parameter |
| `F-wiring` | `wiring` | writable static data (`data`, `bss` or `tls` section, local or external; the `allow_mutable_data` facts of T089); not in tests and fuzzers |

### The syscall and IO table (`profiles.SYSCALL_IO_SYMBOLS`)
Built from the names the product policies' `allow` lists use today (`read`, `write`, `close`, `fsync`, `poll`,
`getaddrinfo`, `send`, `recv`, `mmap`, `nanosleep`, `sysconf`, `getrandom`, `fcntl`, `flock`, `linkat`, ...), minus the
pure libc (`memcpy`, `str*`, `malloc`, `snprintf`, `abort`, `__errno_location`), plus the obvious siblings (the
`open`, `stat`, `socket`, `epoll`, `time`, `stdio` families):

`__fxstat`, `__lxstat`, `__xstat`, `accept`, `accept4`, `bind`, `clock_gettime`, `clock_nanosleep`, `close`, `closedir`, `connect`, `creat`, `dup`, `dup2`, `epoll_create1`, `epoll_ctl`, `epoll_wait`, `fclose`, `fcntl`, `fdatasync`, `fflush`, `fgets`, `flock`, `fopen`, `fprintf`, `fputs`, `fread`, `freeaddrinfo`, `fstat`, `fsync`, `ftruncate`, `fwrite`, `getaddrinfo`, `getenv`, `getpeername`, `getpid`, `getrandom`, `getsockname`, `getsockopt`, `gettimeofday`, `ioctl`, `link`, `linkat`, `listen`, `lseek`, `lstat`, `mkdir`, `mmap`, `mprotect`, `munmap`, `nanosleep`, `open`, `openat`, `opendir`, `perror`, `pipe`, `poll`, `ppoll`, `pread`, `printf`, `pselect`, `putchar`, `puts`, `pwrite`, `read`, `readdir`, `readv`, `recv`, `recvfrom`, `recvmsg`, `rename`, `renameat`, `rmdir`, `select`, `send`, `sendmsg`, `sendto`, `setsockopt`, `shutdown`, `sleep`, `socket`, `stat`, `stderr`, `stdin`, `stdout`, `symlink`, `sysconf`, `time`, `unlink`, `unlinkat`, `usleep`, `write`, `writev`

### Limits, over- and under-reporting
* **F-adapter** reports by name. It over-reports a module that only references `printf` or `stderr` for a debug line,
  and under-reports a syscall not in the table (add it to the table; nothing else changes), a syscall reached through
  a function pointer, `syscall(2)`, or inline asm (the semantic gate bans asm). A call into a dependency's wrapper is
  that dependency's floor, not the caller's.
* **F-concurrent** misses a module that only uses a mutex or atomic type defined in a dependency's header with the
  calls inlined elsewhere; it misses `_Atomic` types used through plain operators (no builtin or symbol appears), and
  it flags a module that merely *references* `pthread_*` (a `system_libs` declaration is not looked at).
* **F-parser** works on the scanner's canonical types, which drop qualifiers and expand typedefs: `const char *` and
  `char *` are the same, `uint8_t *` is `unsigned_char *`, `size_t` is `unsigned_long`. It therefore matches every
  `(char *, int)` pair, a string out-parameter with its capacity included: over-reporting, the safe direction. It
  needs the structure facts (`--structure`); without them, or for a function whose type the scanner could not read
  (`null`), or a variadic or unprototyped one, the rule does not apply (under-reporting). It sees a byte buffer only
  when the length is the *next* parameter, only as a single-level pointer (`char **` is not matched), only in
  functions the module defines and exports; a length-first signature `(size_t, const uint8_t *)`, a struct wrapping the
  buffer, and a callback that receives bytes are missed. Functions defined in headers (`static inline`) are not
  exported, so not seen.
* **F-wiring** counts every writable data object, a `static int counter` in a pure-looking helper included.
  Mutable-data is already an error unless the module's policy has `allow_mutable_data = true` (T089); a module that
  declares it and holds a table is the one `wiring` describes.

## The level floor (`profiles.level_floor`)
`level_floor(graph, levels)` is `{module: level}`: a module is at least the level of every module that depends on it
(directly, or through a chain: the *effective* level of a dependent is the higher of its declared level and its own
floor). The graph is `{dependent: {dependency: edge kind}}`; edges of kind `data` and `port` (the kinds of
`architecture.toml`, docs/layering.md) are exempt. An edge the contract does not allow, or any edge when no
architecture is given, has no kind and counts. When several edges allow one dependency the most permissive one
decides (a `pure` or `composition` edge makes it count). Test and fuzz modules are never dependents (they may depend
on anything). `level_floor_detail` also names the dependent that sets the floor; ties go to the first label. A module
nothing depends on has the floor L1. The product's *declared risk roots* of P003 10.1 are not modelled yet: no input
carries them.

## `rigor policy-check`
```
rigor policy-check --policy P.toml --facts DIR [--structure DIR] [--architecture A.toml]
                   [--require-profiles] [--emit-profiles] [--out F]
```
Judges the modules the policy lists that have facts of kind `c_library` or `c_binary`. Exit 0 PASS, 1 FAIL, 2 on any
defect of an input (missing or malformed policy, facts, structure facts or architecture), like the other judges.

| Finding | Severity | Fields |
|---|---|---|
| `profile-unknown` | error | `module`, `profile` |
| `profile-missing` | info; error with `--require-profiles` | `module` (no `profile` key, or an empty list) |
| `profile-below-floor` | error | `module`, `profile` (the missing one), `floor_rule`, `symbol` (or `function` for `F-parser`) |
| `level-below-floor` | error | `module`, `level`, `floor`, `dependent` |
| `profile-floor` | info | `module`, `floor`, `declared` (one per judged module) |

A module without a profile is not checked against the profile floors (that is what `--require-profiles` is for); one
with an unknown name is not either, its `profile-unknown` is the finding. Level checks use the policy's `level` keys
and run whatever the profiles say.

`--emit-profiles` prints, sorted by label, a `[module."label"]` table with a `profile = [...]` line per judged module:
the floor, `["pure"]` when none applies. The `[module]` header is part of the output so it is valid TOML; merge each
line into the module's existing table (the table cannot be declared twice). The summary goes to stderr then, so stdout
is only the policy text. This is how product policies get migrated.

Tests: `gate/tests/test_profiles.py` (matrix cell by cell at every level, the union rule, every floor rule with a
positive and a negative case, the level floor), `gate/tests/test_profiles_check.py` (findings, the policy key in every
reader, exit codes), and `selftest/profiles.sh` on `selftest/profiles_product/` (facts built on the RE farm; every case
runs twice with byte-identical results).
