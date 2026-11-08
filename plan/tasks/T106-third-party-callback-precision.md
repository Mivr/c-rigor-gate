# T106: `indirect-cycle-possible`: precise callbacks into gate-owned third-party libraries

Repo: `Mivr/c-rigor-gate`. Branch `task/T106`. Read `AGENTS.md`, `docs/structure.md` (sections 2-4: the rule, "by
type", the callback rule, the known limits), `gate/rigor_lib/structure.py`, `gate/rigor_lib/structure_types.py`, their
tests, `docs/third-party.md`, `docs/canaries.md` and the red fixtures `callbackcycle` and `fpcycle`.

## Why
business-apps' `lib/io/tls_stream` (L3) still gets three `indirect-cycle-possible` findings, all from mbedTLS
registrations that the mbedTLS API requires (owner ruling 2026-11-08: documented third-party API requirements are an
allowed exception class; `tls_stream` must meet the full L3 standard):
- `configure` passes `tls_bio_send`/`tls_bio_recv` to `mbedtls_ssl_set_bio` and `mbedtls_psa_get_random` to
  `mbedtls_ssl_conf_rng` (`mbedtls/ssl.h`);
- `prepare` passes `wall_now` to `mbedtls_platform_set_time` (`mbedtls/platform_time.h`);
- `tls_claim` passes `heap_calloc`/`heap_free` to `mbedtls_platform_set_calloc_free` (`mbedtls/platform.h`).
In each, F is the product's `port_connect` (an ops-table entry), which reaches the registering function by direct
calls. The rule fires because a call into outside code "may call back" ANY address-taken function. But vendored,
gate-owned third-party code (`gate//third_party/*`) can only call the function values the product handed to it.

## Change
For a callback site whose callee is defined in a **gate-owned vendored library** L (`gate//third_party/<lib>`; NOT libc,
NOT system libraries, NOT a product module), the possible call-back targets are exactly the product functions whose
address is passed (as an argument value of function or function-pointer type, directly or as a member of a struct
argument the scanner can see) to ANY function of L anywhere in the product: L may store a callback and call it from a
later call into L. The finding becomes: a function C in that set reaches, by direct calls, any call site into L
(C = G included). Everything else keeps today's rule (libc and other outside code keep the conservative untyped rule;
calls through the product's own values keep the typed rule).
- Document it in `docs/structure.md` (rule table, the callback paragraph, known limits: "a vendored library could keep
  a pointer the scanner does not see as passed": say why that is acceptable for gate-owned, reviewed vendored code, or
  why the struct-member case covers it).
- Fail closed: if a site's argument types cannot be read, keep the old rule for that site (info `indirect-untyped-fallback`).

## Tests and canaries
- Unit tests in `gate/tests/test_structure*.py`: the mbedTLS shape (F reaches a registering call, the callbacks do not
  reach any call into L) -> no finding; a callback that itself calls into L (`bio_send` calling `mbedtls_ssl_write`)
  -> finding; a callback passed inside a struct argument -> in the set; libc `qsort(.., cmp)` keeps today's behaviour.
- A new red canary `structure-third-party-callback-cycle` (a vendored-library callback that calls back into the
  library) and a green one; existing `callbackcycle`/`fpcycle` stay red. Update `docs/canaries.md`.

## Acceptance
```sh
python3 -I -B gate/tests/run_parallel.py
selftest/product_checks.sh
selftest/canaries.sh
```
plus: grading business-apps `lib/io/tls_stream` from a clone of `/var/tmp/src/business-apps` at `task/L171`
(`git clone -q /var/tmp/src/business-apps /var/tmp/cache/T106/biz && git -C /var/tmp/cache/T106/biz checkout -q task/L171`,
submodule from `/var/tmp/src/c-rigor-gate`, then point its `gate` at your worktree) shows zero
`indirect-cycle-possible` findings on tls_stream; report the structure gate output for that module.

## Allowed paths
`gate/rigor_lib/structure*.py`, `gate/tests/**`, `docs/structure.md`, `docs/canaries.md`, `selftest/**` (canary
fixtures and expectations, add-only).

## Rules
Use `TMPDIR=/var/tmp/cache/T106/tmp`; never write `/tmp`. Build only with `gate/tools/buck2`. Redirect every output to a
file and read it; never pipe into `tail`/`head`. Long runs via `tools/job`. Never `rm` (`cp -f`). No stash, merge or
push. Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src/c-rigor-hidden`, other worktrees or other cache
dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid
(`readlink /proc/<pid>/cwd`); never `buck2 kill`. 2 CPUs shared. No network.
