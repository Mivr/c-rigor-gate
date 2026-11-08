# Semantic product checks (T004)

T002's suppression scan reads source text, and C can defeat a line regex (a line splice inside
`#pragma`, `_Pr##agma` by token pasting, `__attribute__((x))` behind a macro, inline assembly, a call
spelled through a macro alias). Product code also shares a process with the test framework, so it could
try to forge a result (kill the runner, `_exit(0)`, rewrite the results file). Both are closed by
checking what the compiler and the linker actually saw, as cached build actions on RE.

## 1. `<name>_facts` (rules/facts.bzl, gate/rigor_lib/cscan.py)
`c_library`, `c_binary`, `c_test` and `c_fuzz` each define `<name>_facts`, built in the **release**
platform only (`target_compatible_with = toolchains//:release`). The action reads, per source, the
prelude's own sub-targets of the real compile: `[objects][<unit>][preprocessed]` (the `clang -E -dD` text
of the same compile command, same flags, same toolchain) and the release object. The scanner (stdlib
Python, run on RE) writes one JSON file:

```
{"schema":1,"label":"//pkg:name","kind":"c_library","deps":["//pkg:dep",...],
 "units":[{"name":"a.c.o","defined":[..],"weak":[..],"undefined":[..],
           "pragmas":[{"file","line","text"}],"attributes":[{"name","file","line"}],
           "identifiers":[{"name","file","line"}]}]}
```
* **Preprocessed text:** every `#pragma` line (so `_Pragma`, splices, pasting and digraphs all show up as
  pragma lines), every *watched* identifier outside strings (`cscan.WATCHED_IDENTIFIERS`: `asm`, `__asm`,
  `__asm__`, `_Pragma`, `__pragma`, the alloca spellings and the measured prefix-less builtins below; and
  every identifier with a `cscan.WATCHED_PREFIXES` prefix: `__builtin_`, `__sync_`, `__atomic_`,
  `__c11_atomic_`, `__opencl_atomic_`, `__hip_atomic_`, `__scoped_atomic_`), and every identifier inside
  `__attribute__((...))` / `__attribute((...))` / `[[...]]` (any nesting, any line; digraphs are read as
  their primary spelling). `#define`/`#undef` lines (kept by `-dD`) are not scanned as code: only
  expansions count. Text from a file below the toolchain's own header directories
  (`toolchains//:system-roots`, decided by path, not by the system-header flag a product could set with a
  pragma) is skipped as product text; so are `<built-in>` and `<command line>`, and (T108) the exported header
  trees of the gate-owned third-party libraries (path contains `/art/<gate cell>/third_party/`, passed by
  `rules/facts.bzl` as `--vendor-marker`; a macro such a header defines counts like a toolchain macro for
  `reserved-macro`). Config hashes are removed
  from reported paths. Three more kinds of fact are reported as identifiers (the schema-1 facts file has
  no other place for them; see "Builtins" below): `#define X` / `#undef X` for a product macro directive
  on a reserved name, and `#include <h>` for a toolchain header entered inside a product brace.
* **Symbols:** `llvm-nm -g --format=posix` of the object: defined, weak/indirect defined (`W V i I u`) and
  undefined (`U w v`) external symbols.

The facts action fails the build if the compiler produced a different number of units than `srcs`.
It is a plain cacheable action: unchanged inputs are a cache hit; a source edit that does not change the
preprocessed text and the object is also a hit.

Gate-owned inputs: `toolchains//:libc_symbols` (every symbol the pinned glibc's shared libraries
export, one per line) and `policy/<product>.toml`.

## 2. `rigor facts --gate G --facts DIR --policy P.toml [--libc F] [--out F]`
`DIR` holds one `*.json` per target, the product's and `//ctest:ctest_facts` (nothing else: a stray file,
a symlink, an empty directory, a duplicate label or a malformed file is exit 2). The driver builds
`//...` `_facts` targets (`buck2 build --show-output`) and copies them there.
The two gates are two runs (`--gate semantic-suppressions`, `--gate symbols`, `--libc` required for the
latter), each with its own `--out` like every other gate.

### Gate `semantic-suppressions` (decision table: `rigor_lib/semantic_table.py`)
| Rule | When |
|---|---|
| `pragma` | any `#pragma` in product text after preprocessing |
| `pragma-operator` | `_Pragma` / `__pragma` survives preprocessing |
| `inline-asm` | `asm`, `__asm`, `__asm__` |
| `forbidden-attribute` | an attribute (`__x__` spelling normalised) in `FORBIDDEN_ATTRIBUTES`: `optnone`, `no_instrument_function`, `no_profile_instrument_function`, `disable_sanitizer_instrumentation`, `no_sanitize`, `no_sanitize_address/memory/thread`, `no_address_safety_analysis`, `no_stack_protector`, `weak`, `weakref`, `alias`, `ifunc`, `constructor`, `destructor`, `section`, `used`, `visibility`, `naked`. `noreturn` is allowed. |
| `line-directive` | a line marker the compiler did not write: a flag-less marker that names another file, or goes back in the same file (a user `#line`), or a return marker that does not name the file it returns to. Markers are never believed: the file stays the one the compiler is really reading, so a `#line` naming a system header cannot hide the text after it |
| `banned-builtin` | `alloca`, `__alloca`, `_alloca`, and every `__builtin_alloca*` (`_with_align`, `_uninitialized`, ...). No policy can allow it (`allow_builtins` naming one is exit 2) |
| `forbidden-builtin` | any other builtin (a watched prefix, or a measured prefix-less builtin) that is not in `ALLOWED_BUILTINS`; except `__builtin_trap`/`__builtin_unreachable`/`__builtin_debugtrap` where the module's `allow_builtins` lists it, and `__builtin_setjmp`/`__builtin_longjmp` where the module may reference `setjmp`/`longjmp` (`deny_exempt`, or `allow` when the symbol is not denied) |
| `reserved-macro` | a product `#define`/`#undef` of a reserved identifier (`__x`, `_X`), a C keyword, or a name a toolchain or gate-owned third-party header (or `<built-in>`/`<command line>`) also defines or undefines in that unit. Feature-test macros (`semantic_table.FEATURE_TEST_MACROS`: `_GNU_SOURCE`, `_POSIX_C_SOURCE`, ...; not `_FORTIFY_SOURCE`) are fine |
| `block-scope-include` | a toolchain header entered while a product brace is open (inside a function body or a struct) |

An identifier the scanner reports but the table does not know is exit 2 (table and scanner drifted).

### Gate `symbols`
Policy (`policy/<product>.toml`, gate-owned; any defect is exit 2):
```toml
[global]
deny = [...]                 # nothing may reference these...
trusted = ["//ctest:ctest"]  # gate-owned modules: only their exports count; nothing is checked on them
[module."//core:core"]
allow = ["memcpy"]           # external symbols beyond what its direct deps define
deny_exempt = []             # entries of global.deny this module may use (this also allows them)
allow_builtins = []          # guarded builtins (trap/unreachable/debugtrap) this module may use
level = "L3"                 # L1..L5; read by the exports check (below)
exports = ["core_add"]       # every external symbol the module may define (T033)
system_libs = ["pthread"]    # sysroot libraries its c_library declares, exactly (T095; below)
```
For every non-trusted target: undefined symbols minus its own definitions must be defined by a **direct**
dependency, be in `allow` or in `deny_exempt`. Findings:

| Rule | When |
|---|---|
| `denied-symbol` | references a `global.deny` symbol without `deny_exempt` (wins over `allow`) |
| `undeclared-symbol` | references anything else not defined by a direct dep or allowed |
| `symbol-collision` | defines a symbol the C library or a trusted module exports (interposition) |
| `weak-symbol` | defines a weak, indirect or unique symbol |
| `module-not-in-policy` / `policy-module-without-facts` / `trusted-module-without-facts` | facts and policy disagree |
| `missing-dep-facts` | a declared dep has no facts file |
| `unexpected-export` | defines an external symbol that is not in the module's `exports` list (T033) |
| `exports-missing` | the module is L3 or above and has no `exports` key (T033; info at L2) |
| `unused-allow` | info only (T085): an `allow` or `deny_exempt` entry that no object of the module references (a module with no objects reports every entry; fields `list`, `symbol`, `reason = "not referenced"`), or an `allow` entry that a direct dep's exports already cover (`reason = "covered by <dep>"`). Never changes PASS/FAIL; such an entry only widens what a later change may use without review, so remove it |
| `mutable-global-export` | defines an external object in a writable data/bss section, listed or not (T033; error at L3 and above, info at L2) |
| `system-lib-not-allowed` | a `c_library` declares `system_libs = [..]` and its policy entry does not list the library (T095; field `lib`) |
| `system-lib-not-declared` | the policy entry lists a `system_libs` entry the module's `c_library` does not declare (T095; field `lib`) |
| `mutable-data` | a module without `allow_mutable_data` defines any writable static data, `static` locals included (T089; below) |
| `ram-over-budget` / `ram-unbudgeted` | a binary links more writable bytes than its `ram-budget.toml` entry, or has no entry (T089; below) |

### System libraries (T095)
`c_library(..., system_libs = ["pthread"])` is the only way for a product to link a sysroot library (a
`#pragma comment(lib, ...)` is a `pragma` finding, correctly). The rules accept bare names from an allow-list, `pthread`
only, and the macro fails analysis for any other name, a duplicate, or a non-list. A `c_test`, `c_binary` and `c_fuzz`
take no such argument (`rigor buckfiles`: `bad-argument`). The cross-check is the symbols gate's: `cscan.py` writes the
facts key `system_libs` (sorted; empty for every kind but `c_library`; required in every product facts file, absent
only from gate-owned third-party facts), the policy lists the same set under the module's table, and **both
directions are errors**, so a stale allow cannot wait for a later declaration. A policy or facts file that names a
library outside the allow-list is exit 2. `facts_data.SYSTEM_LIBS` and `rules/c.bzl` `_SYSTEM_LIBS` are the same list; a
unit test pins it. The module still needs `allow = ["pthread_create", ...]` for the symbols it references (libpthread
symbols are not in the libc export list of the pinned glibc 2.31 sysroot), and the global deny list still applies.
Canaries `system-lib-not-allowed` and `system-lib-not-declared` pin both directions end to end.

### Exports policy (T033, R003 G7, backlog B32)
`exports` is the gate-owned allowed set of **defined external symbols** of a module, all units together (a test or
binary lists `main`). Nothing in the product can change it: the policy file is gate-owned like `allow`.
* **Levels** (`level`, the same key the mutants gate reads). L1 is exempt. L2: a defined symbol outside the list is an
  `unexpected-export` (error); a missing list is `exports-missing` as info. L3 and above: a missing list is
  `exports-missing`, an error, so a module at L3 can never pass without a list.
* **Mutable objects.** `cscan.py` reads the nm class of each defined external symbol and writes the unit key `mutable`:
  the objects in writable storage (classes `D B G S C`: data, bss, small data, common; thread-local data is among them).
  `const` data (`R`) and code (`T`) are not. The objects are position independent, so a `const` table of addresses
  sits in `.data.rel.ro` and nm calls it `D`; a second `llvm-nm --format=sysv` listing names the section, and symbols in
  `.data.rel.ro*` (read-only after relocation) are dropped from `mutable`. That second listing can only remove names, so
  output the scanner cannot parse reports more, never less. The selftest pins both on the real toolchain (`x_const`
  lists a `const char *const` table and is only `unexpected-export`). A listed symbol that is mutable is still
  `mutable-global-export`: the list says a name may exist, never that it may be writable. A `const` table that is not
  listed is only `unexpected-export`. The reader requires `mutable` in every product facts file (gate-owned third-party
  facts, which are never checked, may omit it).
* **Where the check is armed.** A module table with neither `level` nor `exports` is not checked (legacy table). An
  `exports` key arms the check even without a level (the level is then taken as L3). `rigor grade` hands the symbols
  gate the policy whole, `level` included (T055), so it checks as `rigor facts` does: L1 is exempt, a missing list at
  L2 is `exports-missing` (info), a missing list at L3 and above is `exports-missing` (error) and fails the gate. A
  `level` that is not `L1`..`L5` is an internal error (exit 2), never "unchecked". The canary `exports-missing-l3`
  pins it end to end.
* **Generating the first list.** Build the product's facts as `rigor grade` does (`<name>_facts` in the release
  platform) and print what each module defines; review the output against the module's public header before pasting it:
  ```sh
  python3 -I -c 'import glob,json,sys
  for f in sorted(glob.glob(sys.argv[1] + "/*.json")):
      d = json.load(open(f)); names = sorted({s for u in d["units"] for s in u["defined"]})
      print(d["label"], "exports = " + json.dumps(names))' FACTS_DIR
  ```
  A symbol a library defines that none of its `headers` mentions is exported but undeclared: remove the export
  (make it `static`) or declare it. Test and binary modules only need `main` plus their own shared test-kit helpers.
  annas-c's lists were generated this way in T033 (its test-kit helpers `kit_*`, `ak_*`, `kf_*` are exported by the
  shared test sources and are listed per test; no library exports an undeclared symbol).

### Static data facts, `allow_mutable_data` and the RAM budget (T089, P002 G26)
Products with a static-memory rule (`Mivr/business-apps`) need to see state that has no external symbol: a
`static int counter;` inside a function of a library is invisible to `exports` and `mutable` (external objects only).
* **Facts.** Every unit of a product facts file carries `data` (required: a product facts file without it is exit 2;
  gate-owned third-party facts may omit it, and then count as 0 bytes and are listed as `unmeasured` in the metadata):
  `"data":[{"name":"f.counter","size":4,"section":"bss","local":true}]`, one entry per defined object, external and local,
  sorted. `cscan.read_data` reads `llvm-nm --defined-only --format=sysv` (all symbols, no `-g`; the Size column is
  hex) and keeps the symbols whose Type is `OBJECT` or `TLS`. `section` is the **class of the section name**, not the nm
  letter (which cannot tell `.data.rel.ro` from `.data`, nor `.tbss` from `.bss`): `ro` for `.rodata*`, `.lrodata*`
  and `.data.rel.ro*`; `data` for `.data*`, `.sdata*`, `.ldata*`; `bss` for `.bss*`, `.sbss*`, `.lbss*` and common;
  `tls` for `.tdata*`, `.tbss*` (and any `TLS` symbol). Objects in other sections (`.init_array`, `.eh_frame`, notes,
  code) are not data. `local` is true for a `static` (lowercase nm class). The existing `mutable` field is unchanged.
* **Policy.** `allow_mutable_data = true` in a module table (default false; any other value is exit 2). A target that is
  not allowed and defines any `data`, `bss` or `tls` object gets `mutable-data` (error) with `target`, `unit`, `symbol`,
  `size`, `section` and `local`. `c_test` and `c_fuzz` targets are exempt (their state is the test's). A testkit
  **library** is not exempt: nothing marks a library as test-only except the product's own words, so a product that wants
  mutable test helpers writes `allow_mutable_data = true` for that module, a gate-owned line that is reviewed. Compiler-generated
  symbols: none are excluded. The facts are built in the release mode, where the compiler adds no program-state symbols
  of its own (coverage counters and sanitizer shadow only exist in the `san` and coverage modes, which these facts never
  see); private `.L` labels are not in the symbol table. An exclusion list will be added by measurement, never by guess.
  A module with an external writable object gets both `mutable-global-export` and `mutable-data`.
* **RAM budget.** For every `c_binary` (never libraries, tests or fuzzers) the gate sums `size` of `data`, `bss` and
  `tls` objects over every unit it links: the binary's own, and those of every library reachable through `deps`;
  product code and trusted third-party code are reported separately in the `symbols` result,
  `metadata.ram[<binary>] = {"product":N,"third_party":M,"total":N+M,"unmeasured":[...]}`. Read-only data is not RAM.
  `products/<p>/ram-budget.toml` (gate-owned, next to `policy.toml`, read with it by `facts_policy.load_policy`) holds
  `[binary."//x:y"]` with `max_bytes = N`; a total above N is `ram-over-budget` (bytes, max_bytes), a binary the file does
  not list is `ram-unbudgeted`; no file means no check. Third-party facts carry `data` too (`third_party/tp_facts.py` loads `cscan.read_data`), so trusted libraries'
  writable data is in `third_party`; a library whose facts have no `data` is listed as `unmeasured`.
  `rigor ratchet` governs the file: spec `[binary."*".max_bytes] direction = "down"` (a `*` path part matches any table name)
  compares the flattened keys `binary."//x:y".max_bytes`; a raise needs a `ratchet` approval scoped
  `ram-budget.toml:binary."//x:y".max_bytes`.
  Canaries: `mutable-data-static-local` and `ram-over-budget`; `mutable-data-allowed` is not needed, because `control`
  (library modules with no writable data, so green on the real toolchain) and `ram-over-budget` (its module has
  `allow_mutable_data = true` and only the budget fails) cover both sides.

## Modes: `<name>_facts_san` and `rigor facts --modes` (T023)
The semantic scan reads the **release** compile, but the `san` tests run the `san` compile. Code that exists in
one of them only (`#if __has_feature(address_sanitizer)`, `__has_feature(undefined_behavior_sanitizer)`, a macro
from a product header that tests either) is invisible to a release-only scan. So every `c_library`, `c_binary`,
`c_test` and `c_fuzz` also has `<name>_facts_san` (`target_compatible_with = toolchains//:san`; rule type `c_san_facts`, the same implementation, named so that `kind(c_facts, //...)`, what `rigor grade` builds in release, does not pick it up): the same rule,
the same scanner, the compile command of the `san` build, cached like the release facts. A `c_fuzz` reads a
`<name>__facts_unit` twin that now builds in release and san. Both `_facts` and `_facts_san` have a `[calls]`
sub-target, `calls.json`: the functions the preprocessed text calls, per unit (`gate/rigor_lib/facts_modes.py scan`;
an identifier followed by `(` in product text, keywords excluded; a declaration counts, so a function that exists
in one mode only is found).

`rigor facts --modes RELEASE_DIR SAN_DIR [--out F]` (gate `mode-divergence`). Each directory holds, per target,
`<name>.json` (the facts file) and `<name>.calls.json`. For every unit, each semantic item present in one
mode and not in the other is a finding `mode-divergent-code` with `target`, `unit`, `only_in` (`release`|`san`),
`item_kind` (`pragma`, `attribute`, `line-directive`, `identifier` (asm, builtins, `#define`/`#undef` of reserved
names, denied identifiers charged through toolchain code), `call`), `item`, `file`, `line`. The line is part of the
item. Symbol facts (`defined`/`weak`/`undefined`) are never compared: the sanitizer runtime legitimately changes them.
Comments do not survive preprocessing in either mode, so they cannot differ.

**The legitimate difference, and why there is no knob.** The gate's own sealed flags differ between the modes
(`-O1 -fsanitize=...` against `-O2`), and so do the macros they define and what toolchain headers do with them.
All of that is `<built-in>`, `<command line>` or text under the toolchain's header roots, which the scanner never
treats as product text. Anything the product itself writes (in a `.c`, in its own header, through its own macro) that
differs is a finding, at every level; there is no policy entry that allows it. A sanitizer-conditional product line is
the way R001 R5 hid things, and a production build has no use for one.

Fail closed (exit 2, never a pass): a directory that is empty, missing or holds anything but regular `*.json`; a facts
file or calls file that is malformed or has another schema; a facts file without its `.calls.json` (or the reverse); a
calls file whose label differs from its facts; a target or a unit in one mode only (a module with no `san` twin).
Gate-owned `c_third_party` facts are skipped in both directories.

What this toolchain does and does not make differ (measured): `__has_feature(address_sanitizer)` and
`__has_feature(undefined_behavior_sanitizer)` differ (found). `__SANITIZE_ADDRESS__` is a GCC macro that the pinned
clang 19 does not define under `-fsanitize=address`, so code under it is dead in both modes (not a divergence).
`NDEBUG` is defined in neither mode and both modes optimise (`__OPTIMIZE__` is defined at `-O1` and `-O2`), so
code under `#ifndef NDEBUG` or `#ifdef __OPTIMIZE__` is the same text in both (and visible to the release scan).
Wiring into `rigor grade` is a later task.

## 3. `rigor buckfiles --root DIR [--out F]` (gate `buckfiles`)
Each `BUCK` is parsed (never executed) with `ast`. Allowed: `load("@gate//rules:c.bzl", ...)` naming only
`c_library`, `c_binary`, `c_test`, `c_fuzz`, `c_catalog`, `c_embed` (T112: `name`, `visibility`, `src` and `symbol` strings, `max_bytes` one int literal; docs/grade.md, "`c_embed`"), and top-level calls to those with keyword arguments
(`name`, `srcs`, `headers`, `deps`, `visibility`; `c_library` also `system_libs` and `exported_deps`, T110, a `deps`-like list) whose values are string literals or lists of string
literals. Rules: `bad-load`, `extra-load` (a second `load`), `bad-call` (`native.`, other rules, wrappers),
`bad-argument` (positional, `**`, unknown keyword, non-literal value, a `deps` entry that is not a same-cell label `:name` or `//pkg:name` (why=`dep`: no cell prefix, so no raw rules or prelude targets; the macros add `gate//ctest:ctest` themselves), `glob`, `select`, concatenation,
f-strings), `bad-statement` (assignment, `def`, `if`, `for`, import, bare expression), `parse-error`
(also non-UTF-8 and NUL), `forbidden-file` (any file Buck2 could read as configuration: `*.bzl`, `*.bxl`,
`BUCK.*` such as `BUCK.v2` which wins over `BUCK`, `TARGETS*`, `PACKAGE*`, `.buckconfig*`, `.buckroot`,
`.buckignore`, `.buckjavaversion`, and `buck`/`Buck` spellings), `symlink` (any symlink anywhere).

## Builtins (T014)
The symbol deny list and `-Wframe-larger-than` are keyed on symbols and static frames; a compiler builtin
has neither (`__builtin_alloca` is a stack adjustment, `__builtin_setjmp`/`__builtin_longjmp` are
intrinsics, `__builtin_frame_address` reads a register). Enumerating the dangerous ones fails open, so
builtins are **default-deny**: every identifier of a builtin family is a fact, and only the allowlist passes.

**Measurement.** Builtins without a family prefix were found by asking the pinned clang (19.1.7,
`--target=x86_64-unknown-linux-gnu -std=c17`, also with `-march=sapphirerapids`, `-march=znver4` plus AMD
extensions, and `-std=gnu17`) `__has_builtin(X)` for every identifier string in the `clang-19` binary
(1 109 175 candidates, a genrule on RE). 3 134 are builtins: 2 543 `__builtin_*`, 107 `__sync_*`, 30
`__atomic_*`, 24 `__scoped_atomic_*`, 17 `__c11_atomic_*`, 13 `__opencl_atomic_*`, 12 `__hip_atomic_*`,
and 388 others. Of those: C library functions (`memcpy`, `setjmp`, `abort`, the math functions, ...) are
calls that keep their symbol, so the `symbols` gate judges them (`alloca` is only a builtin in GNU mode,
but is banned by name anyway); `va_start`/`va_end`/`va_copy` are the `<stdarg.h>` names;
`__is_target_*`, `__is_destructible` and similar are compile-time queries; `_Block_object_*`, `__sinpi`,
`savectx` and the like are calls to symbols glibc does not have (`undeclared-symbol`). What is left has
no symbol and is watched by name: `__rdtsc`, `_mm_clflush`, `_mm_getcsr`, `_mm_setcsr`, `_mm_lfence`,
`_mm_mfence`, `_mm_sfence`, `_mm_pause`, `_mm_prefetch`, `__arithmetic_fence`, `__xray_customevent`,
`__xray_typedevent`. A toolchain bump must repeat the measurement.

**Allowlist** (`semantic_table.ALLOWED_BUILTINS`, gate-owned, the same for every module). Measured: annas-c
`main` (all 123 units, including the ones its `product.toml` layout does not yet include) and the ctest
runtime expand to `__builtin_va_start`, `__builtin_va_arg`, `__builtin_va_end` (app/tests/parse_err_test.c)
and to nothing else of a builtin family.
| Builtin | Why it is allowed |
|---|---|
| `__builtin_offsetof` | what `<stddef.h>` `offsetof` expands to; a compile-time constant |
| `__builtin_va_start`, `__builtin_va_arg`, `__builtin_va_end`, `__builtin_va_copy` | what `<stdarg.h>` expands to (annas-c uses the first three); they only walk the current function's own variadic arguments, no symbol, no stack growth. The gate has no header policy, so `<stdarg.h>` is allowed everywhere and so are these |
| `__builtin_add_overflow`, `__builtin_sub_overflow`, `__builtin_mul_overflow` | checked arithmetic (C23 `ckd_add`/`ckd_sub`/`ckd_mul`), the tool the C rules want for size computations; pure, no memory access beyond the result pointer |
`__builtin_expect` is **not** allowed: nothing measured needs it. Measured but not needed by annas-c, and so
denied until a product needs them: `<math.h>` (`HUGE_VAL`, `NAN`, `INFINITY`, `isnan`, `isinf`, `signbit`
expand to `__builtin_huge_val`, `__builtin_nanf`, `__builtin_inff`, `__builtin_isnan`, ...), glibc's
`tolower`/`toupper` at `-O2` (`__builtin_constant_p`), `<stdatomic.h>` (`__c11_atomic_*`).

**Every spelling that reaches a builtin**, and what covers it (red fixtures in `selftest/product_checks.sh`
step "builtins ...", unit tests in `gate/tests/test_cscan_builtins.py` and `test_facts_builtins.py`):
* a macro, token pasting (`CAT(__builtin_, alloca)`), a line splice inside the name: the scan reads the
  preprocessed text, so the use appears under its final spelling at the line of the use (reds `b_paste`,
  `b_hidden`).
* `__has_builtin(X)` only asks; outside `#if` it expands to `1`/`0` and the name is gone. It cannot call
  anything, so it is not a fact.
* `#pragma push_macro`/`pop_macro` (also through `_Pragma`) are consumed by the preprocessor and do not
  appear in `-E -dD` text (measured), so they are not `pragma` findings; they only save and restore macro
  definitions, and whatever builtin the final expansion names is in the text and is found. Changing a
  macro needs a `#define`/`#undef`, which is in the text.
* `_Pragma(...)` that survives preprocessing is a `#pragma` line (`pragma`); `_Pragma` itself left over is
  `pragma-operator`. A pragma cannot name a builtin into code.
* `__attribute__((cleanup(f)))`: `f` is an identifier of product text, so a builtin named there is a fact,
  and a toolchain function named there is charged as below.
* builtins pulled in through system headers: a **macro** from a toolchain header (`alloca`, `offsetof`,
  `va_start`, `atomic_fetch_add`, ...) expands at the product's line, so the builtin is a fact there. A
  **function** defined in a toolchain header (`static inline`, `extern inline`) runs builtins or inline asm
  from text that is skipped: `cscan.ToolchainCode` keeps, for every function defined (and object
  initialised) in toolchain text, the identifiers of its body, and a product identifier that names one is
  charged with every watched identifier the body reaches, transitively (`<sys/io.h>` `inb` is `inline-asm`
  at the call, red `b_io`; `_rdrand32_step` is `__builtin_ia32_rdrand32_step`; `__get_cpuid` is `__asm`).
  Header-declared builtins with plain names (`_mm_lfence`, `__rdtsc`) are watched by name. Fail closed:
  when the toolchain text stops having the shapes real headers have (a `}` that closes nothing, a
  definition whose name cannot be read, a body still open when product text resumes, file-scope `asm`),
  every watched identifier of toolchain text from there on is reported where it is. All 123 annas-c units,
  ctest and a 65 878-line unit including 47 glibc/clang headers with `_GNU_SOURCE` and `<x86intrin.h>`
  parse without that happening and with nothing charged.
* product macros that rewrite a toolchain header: a product macro expanded inside toolchain text puts
  product tokens at a toolchain location, which is skipped. `reserved-macro` stops it for the names
  toolchain headers use for their internals (all reserved: `__THROW`, `__inline`, parameter names like
  `__port`), for keywords, and for every macro the toolchain defines (`NULL`, `stdin`, `assert`, `EOF`,
  ...); `block-scope-include` stops toolchain text from becoming statements of a product function.
  annas-c defines only `_GNU_SOURCE` and `_POSIX_C_SOURCE`.

**Compiler-side guard** (`rules/c.bzl`, sealed flags): `-D__builtin_alloca(...)=__builtin_alloca(c_rigor_gate_bans___builtin_alloca)`
and the same for `__builtin_alloca_uninitialized`, `__builtin_alloca_with_align`,
`__builtin_alloca_with_align_uninitialized`, `__builtin_frame_address`, `__builtin_return_address`: a call
is a compile error (`use of undeclared identifier 'c_rigor_gate_bans_...'`). It is function-like and
self-referential, so toolchain macros that merely mention the builtin are unaffected and the preprocessed
text still names the builtin. `#pragma clang poison` was not used: poisoning makes glibc's `<alloca.h>`
(pulled in by `<stdlib.h>` under `_GNU_SOURCE`/`_DEFAULT_SOURCE`) an error, and a forced-include header
would need a file outside T014's paths. `#undef` defeats the guard; that is `reserved-macro`, and the
use is still `banned-builtin` (reds `b_alloca`, `b_paste`, `b_frame`). The selftest builds a 47-header
unit, `examples/hello`, ctest and an annas-c-like green in release, san, cov and fuzz with the guard.

## Line markers
The compiler writes flag 1 (enter include) and flag 2 (return) markers itself; the only flag-less markers it
writes are the first one of the text and forward resynchronisations in the same file. The GNU form
`# N "file" 1` in source is refused by the sealed flags (`-Wgnu-line-marker` under `-Wpedantic -Werror`; selftest
step "the GNU line-marker form ... does not compile"), so a product cannot forge a flag. Standard `#line`
(also spliced) always produces a flag-less marker and is reported.

## Known limits
* A `#line N` that only moves forward in the same file is indistinguishable from the compiler's own
  resynchronisation and is not reported (it only changes the line numbers of later findings; it cannot
  rename the file). Backward moves and renames are reported.
* Facts are release-only. Code under `#ifdef __SANITIZE_ADDRESS__` or `__has_feature(...sanitizer)` is
  not in the release text; those spellings stay forbidden by T002's line patterns, and a red-team case
  should try to rebuild them through macros.
* The scan sees what the compiler sees: it cannot judge an `-fno-...` flag (the macros take none).
* `symbols` judges external symbols. A product module may not reference a symbol outside its allow list,
  but the allow list itself is only as strict as the policy file the owner signs off.
* The policy `deny` list in `policy/hello.toml` is the contract's list plus a few aliases of the same
  powers (`environ`, `putenv`, `posix_spawn`, `clone`, ...).
* Contract wording: the task text listed `weak, alias, constructor, ... noreturn` under "is allowed". It is
  implemented as the forbidden list with `noreturn` allowed; the contract should be confirmed.

* T014 residual: a product macro named like a toolchain identifier that is neither reserved nor a
  toolchain macro (a typedef or function name such as `size_t` or `getc`), defined before the header is
  included, can still rewrite that header's file-scope text. Code it adds there is charged when the
  product names it, and it cannot become statements of a product function (`block-scope-include`); but
  attributes (`constructor`), `#pragma` lines or declarations it adds at file scope are not scanned.
  Closing it needs the toolchain headers' identifier vocabulary as an input of the facts action
  (`rules/facts.bzl`, `toolchains/`), outside T014's paths.
* `__has_builtin`, `push_macro`/`pop_macro` and `#pragma clang poison` leave no trace in `-E -dD` text
  (see "Builtins"); none of them can call a builtin.

## 4. Gate `layering` (T087)
The module boundaries of a monorepo product are a gate-owned contract, `products/<p>/architecture.toml`, judged on the same facts
as `symbols` (direct `deps`, undefined symbols, exports). Findings: `ungoverned-module`, `undeclared-edge`, `upward-edge`,
`edge-kind-violation`, `contract-stale`. Format, edge kinds and limits: [layering.md](layering.md).

Self-test: `selftest/product_checks.sh`.
