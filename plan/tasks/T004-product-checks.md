# T004: semantic product checks on RE (preprocessed scan, symbol allowlists, BUCK guard)

Repo: `Mivr/c-rigor-gate`. Branch `task/T004`. Read `AGENTS.md`, `plan/phase1.md`, `docs/toolchain.md`,
`docs/ctest.md`, `docs/gate.md` first.

## Why
The T002 suppression scan reads source text, and C can defeat that (line splices, macro token pasting, includes).
Product code and test code also share a process with the test framework, so product code could in principle forge
a result (kill the runner, `_exit(0)`, rewrite the results file). Both are closed by checking what the compiler
and linker actually see, on RE, as cached build actions:
1. the **preprocessed** translation unit of every source, and
2. the **symbols** every object defines and references.

## Allowed paths
`rules/**`, `toolchains/**` (only to expose `llvm-nm` and clang `-E` as tools), `gate/**` (new subcommands and
their tests; do not weaken existing ones), `policy/**`, `examples/**`, `selftest/product_checks.sh`,
`docs/product-checks.md`.

## 1. Fact actions (Buck2, RE, cached)
Every `c_library`, `c_binary`, `c_test`, `c_fuzz` additionally defines `<name>_facts` (release platform only),
an action that outputs one JSON file:
- for each source: the result of scanning `clang -E` output (same flags as the real compile, same toolchain);
- for each object: `llvm-nm` defined and undefined symbol lists (release mode objects, so no sanitizer or
  profile symbols appear).
The scan itself is a gate-owned Python script run in the action. Facts are data; the decision is in `rigor`.

Preprocessed scan findings (any occurrence in the TU, after preprocessing):
- `#pragma` lines (`_Pragma` turns into these), except none; `#pragma once` is not needed (use include guards).
- `__attribute__((...))` / `[[...]]` mentioning `optnone`, `no_instrument_function`,
  `no_profile_instrument_function`, `disable_sanitizer_instrumentation`, `no_sanitize`, `weak`, `alias`,
  `constructor`, `destructor`, `section`, `used`, `visibility`, `noreturn` is allowed.
- `asm` / `__asm__` / `__asm` (inline assembly).
- identifiers `__builtin_trap`, `__builtin_unreachable` outside the `core` assert module (configurable).

## 2. Symbol policy (gate-owned)
`policy/<product>.toml`:
```toml
[global]
deny = ["kill", "fork", "vfork", "execve", "execv", "execvp", "execl", "ptrace", "_exit", "_Exit",
        "exit", "quick_exit", "abort_handler_s", "signal", "sigaction", "raise", "dlopen", "dlsym",
        "syscall", "getppid", "setjmp", "longjmp", "_setjmp", "sigsetjmp", "siglongjmp", "atexit",
        "at_quick_exit", "system", "popen", "mprotect", "prctl", "unlink", "rename", "remove",
        "rand", "srand", "random", "time", "clock_gettime", "gettimeofday", "getenv",
        "fopen", "open", "openat", "creat", "socket", "connect", "dup2", "dup3", "pipe", "pipe2"]
# test objects get the same deny list; the ctest runtime target is exempt by label.

[module.<label>]          # e.g. "//core:core"
allow = ["memcpy", ...]   # undefined symbols this module may reference, beyond its own deps' exports
deny_exempt = []          # entries of [global].deny this module may use (e.g. the fs adapter: open)
```
A module may reference only: symbols defined by its declared deps, plus its `allow` list. Anything else, and any
`global.deny` symbol not in `deny_exempt`, is a finding. A product module missing from the policy is a finding.
Defined symbols that collide with libc or ctest symbols (interposition, e.g. defining `write` or
`ctest_report`) are a finding.

## 3. BUCK guard
`rigor buckfiles --root DIR`: every `BUCK` under DIR is parsed with Python `ast` (Starlark syntax used is a
Python subset). Allowed: exactly one `load("@gate//rules:c.bzl", ...)` naming only `c_library`, `c_binary`,
`c_test`, `c_fuzz`; top-level calls to those names with keyword arguments whose values are string literals or
lists of string literals. Anything else (assignments, other calls, `native.`, comprehensions, `glob`, other
loads, `.bzl` files anywhere in the product) is a finding; a parse failure is a finding.

## 4. `rigor` subcommands
`rigor facts --facts DIR --policy P.toml --out ...` (gates `semantic-suppressions` and `symbols`) and
`rigor buckfiles`. Same conventions as T002: exit 0/1/2, fail closed, deterministic findings, red test first.

## Self-test `selftest/product_checks.sh`
Throwaway product packages proving each rule red and green on real RE builds, including: a pragma made by
token pasting, a pragma behind a line splice, a forbidden attribute via a macro, inline asm, a call to `kill`
via a macro alias, `_exit(0)` in a test, a module calling `fopen` without exemption, defining `write`,
a BUCK file with an assignment, with `native.cxx_library`, with a second load, and a `.bzl` file in the product.
Also: all facts actions are cache hits on a second run.

## Acceptance
```sh
selftest/product_checks.sh     # twice in a row, exit 0
selftest/gate.sh               # still green
selftest/ctest.sh && selftest/toolchain.sh   # still green
```
