# T009: gate-owned third-party C libraries (mbedTLS 3.6 LTS first)

Repo: `Mivr/c-rigor-gate`. Branch `task/T009`. Read `AGENTS.md`, `plan/phase1.md`, `docs/toolchain.md`,
`docs/product-checks.md`, `docs/grade.md`. T008 runs in parallel (grade pipeline, mutants, products/): do not
touch `gate/rigor_lib/grade*.py`, `gate/rigor_lib/mutants_*.py`, `gate/order.txt`, `products/**`.

## Why
Products need a few vetted C libraries (first: TLS for annas-c). Third-party code cannot meet product rules and must
not be editable by product agents, so it lives in the gate: pinned by sha256, built hermetically on RE, exposed
through a fixed label, with its exported symbols known to the policy.

## Allowed paths
`third_party/**`, `rules/**` (a `c_third_party` rule; do not weaken the product macros), `toolchains/**` (only if
needed), `gate/rigor_lib/buckfiles.py`, `gate/rigor_lib/facts_*.py`, `gate/tests/test_buckfiles.py`,
`gate/tests/test_facts.py`, `selftest/third_party.sh`, `docs/third-party.md`.

## Requirements
1. `third_party/mbedtls/`: mbedTLS **3.6.x LTS** release tarball from `github.com/Mbed-TLS/mbedtls/releases`,
   pinned by sha256 (`http_archive` or the T001 `fetched_tree`), built as a static library with the gate's
   hermetic toolchain (its own flag set: C99/C17, `-O2`, warnings not fatal for vendored code), a gate-owned
   `mbedtls_config.h` enabling only TLS 1.2 + 1.3 client, X.509 parsing, PEM, ECDHE/ECDSA/RSA, AES-GCM,
   ChaCha20-Poly1305, SHA-2, the PSA crypto core, and **no** server, no SSLv3/TLS1.0/1.1, no
   `MBEDTLS_FS_IO` except the CA file loader, no debug, no net_sockets (the product supplies the BIO).
   Entropy: `getrandom` only.
   It must also build in `san` mode.
2. A product may depend on it only via the exact label `gate//third_party/mbedtls:mbedtls`, and only from
   modules whose policy entry lists it: extend `buckfiles` to accept exact labels from a gate-owned allowlist
   (`third_party/ALLOWED_LABELS`, one per line) as `deps` entries, everything else still `bad-argument`.
3. Facts and symbols: a vendored library is `trusted` for the scan (not scanned), its exported symbols are
   computed by the build (a `_symbols` target) and count as "dependency exports" for the modules that depend on
   it, and as reserved names (a product may not define `mbedtls_*` or `psa_*` symbols).
4. `docs/third-party.md`: the pin, the config rationale, how to bump (owner-approved task only).

## Self-test `selftest/third_party.sh`
A throwaway product module that does a TLS 1.3 handshake **against an in-memory loopback BIO** with an embedded
test CA and server (server code may live only in the self-test, using a second gate-owned config if needed),
proving the library links and works in `release` and `san`; a module depending on it without policy
permission fails `symbols`; a BUCK dep on any other third-party-looking label fails `buckfiles`; a product
defining `mbedtls_ssl_read` fails `symbols` (collision).

## Acceptance
```sh
selftest/third_party.sh    # twice
selftest/product_checks.sh && selftest/gate.sh && selftest/toolchain.sh
```
Report the pin (URL, sha256), the config, library size, build time cold/warm, and deviations.
