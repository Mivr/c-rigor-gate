# T119: refresh `products/business-apps` (refresh 4: lvhost, input, checkconfig, posixio, cabundle, posix_fs, e2eclock L3, wire atomics)

Repo: `Mivr/c-rigor-gate`. Branch `task/T119` from main (T118 merged: `__atomic_load_n`/`__atomic_store_n` are guarded
builtins a module may list in `allow_builtins`). Use the same method, rules and four files as T111, T113 and T116. Read
`plan/tasks/T111-business-apps-config-refresh.md`, `T113-...` and `T116-business-apps-config-refresh-3.md` first. The
differences are below.

- **Product.** `Mivr/business-apps`, local clone `/var/tmp/src/business-apps` (main at the L297 merge or later; gate
  pointer `08c4e75`). Read-only for you: clone it into `/var/tmp/cache/T119/biz-clone` exactly as T111 did, and grade
  the clone. Cover every module on `main` when you clone, and list them. New or changed since T116 started (check each):
  - `lib/ui/lvhost` (L2, L294/L297): the THIRD module allowed `gate//third_party/lvgl:lvgl` (after uikit and lvrender).
  - `apps/lockers/lkui/input` (L3, L293/L296).
  - `apps/lockers/lkui/notices` (dense keys, dismiss arg; L292/L295).
  - `apps/lockers/lkapp/checkconfig` (L279/L287) and `apps/lockers/lkapp/posixio` (L272/L282): posixio is the POSIX
    adapter; give it the minimal `allow`/`deny_exempt` its facts need (open, socket, connect, fstat, mkdir, ...: list
    them from the facts, nothing extra) and say each one.
  - `lib/io/posix_fs`: new exports `posix_fs_op_replace`, `posix_fs_write_all`, `posix_fs_c_unlinkat` (L284/L286).
  - `apps/lockers/lkadp/e2eclock`: raise to **L3** (L291 killed the survivors; one equivalent is signed).
  - `apps/lockers/lkapp/wire`: add `allow_builtins = ["__atomic_load_n", "__atomic_store_n"]` (T118), plus the L281/
    L288/L289 changes (threads, world split).
  - `apps/lockers/lkrx/fold_core`: new export `lk_book_was_uncertain` (L298; the macro is gone, so `put_done` in
    `lkrx/shift` no longer hides code).
  - `lib/io/cabundle` (L1, L299): a `c_embed` (`nul = True`) of `cacert.pem` plus `LICENSE-MPL-2.0.txt` and one
    `c_test`; `product.toml` layout must include the `.pem` and the licence (as fontdata's `.ttf`).
  - `lkapp/runtime`, `lkui/scene*` (L283/L285) and anything else the clone shows without a policy entry.
- **Not on main yet, do NOT add:** `apps/lockers/lkapp/uiloop`, `apps/lockers/lkapp/shell_linux`. No `ram-budget`
  entry yet (no kiosk binary exists; refresh 5 adds it).
- **Expected ids.** Add-only, taken from real release and san results with `gate/tools/expected.py add`. If an expected
  id no longer exists, report it; remove one only with a signed `test-removal` approval in the staged approvals.
- **Approvals.** Grade with `--approvals /var/tmp/cache/T119/approvals` (read-only copy of the orchestrator's signed
  approvals: 152 `.json`, each with its `.json.sig`). Never write or edit approvals. Report matched, rejected and unused.
- **Mutants.** Report every uncovered L3/L4 survivor (file:line, mutation), L2 survivor counts per module (info), and any
  `mutants-build-failed`. The T116 grade's two product findings (`forbidden-builtin` in wire, `macro-hidden-code` in
  shift) must now be gone; say so or show what remains.
- **Report.** The whole-repo grade verdict per gate, and product findings. Never edit product code.

## Allowed paths
`products/business-apps/**`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
```
plus the final whole-repo grade verdict summary in the report.

## Rules
- As T111, with worktree `/var/tmp/wt/c-rigor-gate/T119`, `TMPDIR=/var/tmp/cache/T119/tmp` and cache dir
  `/var/tmp/cache/T119`. Long runs via `tools/job`.
- Never `rm`; never `buck2 kill`; kill only your own buck2d, by pid (`pgrep -f '^buck2d\['` plus a cwd check, never
  `pgrep -f buck2d`).
- Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache
  dirs. Never search from `/` or `/var/tmp`. Never print the environment. **Never use the Agent tool.** No stash, merge
  or push.
- Redirect every output to a file and read it; never pipe into `tail` or `head`.
- One grade at a time. Use `--deadline 14400`. No network except Buck2's pinned downloads. 16 GiB is shared by three
  lanes. Commit on `task/T119` when done; your last message is the report.
