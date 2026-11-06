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
  pragma lines), every identifier of `cscan.WATCHED_IDENTIFIERS` (`asm`, `__asm`, `__asm__`, `_Pragma`,
  `__pragma`, `__builtin_trap`, `__builtin_unreachable`, `__builtin_debugtrap`) outside strings, and every
  identifier inside `__attribute__((...))` / `__attribute((...))` / `[[...]]` (any nesting, any line).
  `#define`/`#undef` lines (kept by `-dD`) are skipped: only expansions count. Text from a file below the
  toolchain's own header directories (`toolchains//:system-roots`, decided by path, not by the
  system-header flag a product could set with a pragma) is skipped; so are `<built-in>` and
  `<command line>`. Config hashes are removed from reported paths.
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
| `forbidden-builtin` | `__builtin_trap`, `__builtin_unreachable`, `__builtin_debugtrap`, unless the module's policy entry lists it in `allow_builtins` |

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
allow_builtins = []          # guarded builtins this module may use
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

## 3. `rigor buckfiles --root DIR [--out F]` (gate `buckfiles`)
Each `BUCK` is parsed (never executed) with `ast`. Allowed: `load("@gate//rules:c.bzl", ...)` naming only
`c_library`, `c_binary`, `c_test`, `c_fuzz`, and top-level calls to those with keyword arguments
(`name`, `srcs`, `headers`, `deps`, `visibility`) whose values are string literals or lists of string
literals. Rules: `bad-load`, `extra-load` (a second `load`), `bad-call` (`native.`, other rules, wrappers),
`bad-argument` (positional, `**`, unknown keyword, non-literal value, `glob`, `select`, concatenation,
f-strings), `bad-statement` (assignment, `def`, `if`, `for`, import, bare expression), `parse-error`
(also non-UTF-8 and NUL), `forbidden-file` (any file Buck2 could read as configuration: `*.bzl`, `*.bxl`,
`BUCK.*` such as `BUCK.v2` which wins over `BUCK`, `TARGETS*`, `PACKAGE*`, `.buckconfig*`, `.buckroot`,
`.buckignore`, `.buckjavaversion`, and `buck`/`Buck` spellings), `symlink` (any symlink anywhere).

## Known limits
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

Self-test: `selftest/product_checks.sh`.
