# T127: module profiles, computed floors and the technique matrix as a pure library (P003 W3 part 1)

Repo: `Mivr/c-rigor-gate`. Branch `task/T127` from main. Read P003 §4 and §10.1 in full, then
`gate/rigor_lib/grade_policy.py`, `facts_policy.py`, `facts_symbols.py`, `facts_data.py`, `structure_data.py`
(`type` of a function, T063), `layering.py` (edge kinds), `docs/product-checks.md`, `docs/layering.md`.

## Why
In v1 a level only tunes mutation. P003 gives each module a **profile** (what kind of code it is: `pure`, `parser`,
`adapter`, `concurrent`, `wiring`, `ui`, `safety`); the profile picks the techniques and the level picks how much. There
is no human in the loop, so a profile or a level must not be loosened by declaration: the gate computes a **floor**
from facts it already has, and policy may only add. This task is the pure library and a judge. It changes no gate of
`rigor grade` and no product policy.

## Do
1. **`gate/rigor_lib/profiles.py`** (pure, stdlib only, no IO):
   - the seven profile names, and the technique matrix of P003 §4.1 as one data table;
   - `required(profiles, level) -> {technique: "gate" | "report"}`: the union over a module's profiles, where `gate`
     wins over `report`, with the level conditions of the table (`L3+`, `L2+`, `L4`);
   - `profile_floor(module_facts) -> set of profiles`, rules, each with a rule id that the finding names:
     - **F-adapter**: an undefined symbol from the syscall and IO table (one constant table: `open`, `openat`, `read`,
       `write`, `close`, `fsync`, `rename`, `socket`, `connect`, `send`, `recv`, `poll`, `getaddrinfo`, `clock_gettime`,
       ... ; build it from the names the product policies' `allow` lists use today, and list it in the docs), or from a
       gate-owned third-party library (the reserved prefixes the `symbols` gate already knows);
     - **F-concurrent**: an undefined `pthread_*`, `thrd_*`, `mtx_*`, `cnd_*` symbol, or an `__atomic_*` / `__sync_*`
       builtin in the semantic facts;
     - **F-parser**: an exported function with a parameter of type pointer to `const` `char`, `unsigned char`,
       `uint8_t` or `void` that is followed by an integer parameter (a byte buffer and its length). Over-reporting is
       the safe direction; say in the docs which shapes you match;
     - **F-wiring**: mutable static data (the `allow_mutable_data` facts);
     - `pure` when none of the above applies. `ui` and `safety` are never floors; they are declared only.
   - `level_floor(graph, levels) -> {module: level}`: a module is at least the level of every module that depends on
     it; `data` and `port` edges are exempt (the kinds of `architecture.toml`).
2. **Policy key.** `[module."//pkg:name"] profile = ["pure", "parser"]` (a list of names; a single string is also
   accepted). Every reader of `policy.toml` must accept the key and ignore it, so an existing gate behaves exactly as
   before with or without it. Name every file you had to touch for this in your report.
3. **`rigor policy-check --policy P.toml --facts DIR [--structure DIR] [--architecture A.toml] [--require-profiles]
   [--emit-profiles] [--out F]`** in `gate/rigor_lib/policy_check.py`, fail closed like the other judges. Findings:
   - `profile-unknown` (error); `profile-missing` (info; an error with `--require-profiles`);
   - `profile-below-floor` (error): module, the missing profile, the rule id, the symbol or function that triggered it;
   - `level-below-floor` (error): module, its level, the floor, the dependent that sets it;
   - info `profile-floor` per module with the computed floor.
   `--emit-profiles` prints, sorted, one `profile = [...]` line per module (the floor, or `["pure"]`), ready to paste
   into a policy: this is how product policies get migrated in a later task.
4. **Tests and selftest.** Unit tests `gate/tests/test_profiles*.py` for every floor rule (a positive and a negative
   each), the matrix (every cell of P003 §4.1), the union rule and the level floor. A selftest `selftest/profiles.sh`
   on a small product under `selftest/profiles_product/` built for its facts: a module that calls `read` declared
   `pure` (FAIL `profile-below-floor`, F-adapter); a `(const uint8_t *, size_t)` API declared `adapter` only (FAIL,
   F-parser); a module at L2 that an L3 module depends on (FAIL `level-below-floor`); the corrected policy (PASS);
   `--emit-profiles` output pasted back passes. Each twice with identical results.
5. `docs/profiles.md` (the profiles, the matrix, every floor rule with its limits and known over- and under-reporting),
   `tools/affected.toml`.

## Not in this task
`gate/rigor_lib/grade*.py`, `gate/order.txt`, `products/**` (another lane is working there), the arbiter, the ledger,
any use of the matrix by an existing gate.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/product_checks.sh`; `selftest/profiles.sh` twice in a row;
`python3 -I tools/affected.py --check`. Also run, read-only, `rigor policy-check --emit-profiles` on the facts of
`selftest/grade_product` and put the output in your report.

## Allowed paths
`gate/rigor_lib/profiles.py`, `gate/rigor_lib/policy_check.py`, `gate/rigor_lib/cli.py` (registering the subcommand
only), the policy readers as item 2 requires (key acceptance only), `gate/tests/test_profiles*.py`,
`selftest/profiles.sh`, `selftest/profiles_product/**`, `docs/profiles.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T127`. `TMPDIR=/var/tmp/cache/T127/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. Commit on `task/T127`; your last message is the report (what works, what does not, every deviation).
