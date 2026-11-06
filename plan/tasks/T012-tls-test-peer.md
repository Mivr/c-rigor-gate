# T012: product-usable TLS test peer (server-enabled mbedTLS, test targets only) and a test PKI

Repo: `Mivr/c-rigor-gate`. Branch `task/T012`. Read `AGENTS.md`, `docs/third-party.md`, `docs/product-checks.md`,
`third_party/selftest/**` (T009's renamed server copy `srv_*`, already working in one process with the
client-only library). **T008 runs in parallel**: don't touch `gate/rigor_lib/grade*.py`,
`gate/rigor_lib/mutants_*.py`, `gate/order.txt` or `products/**`. **T011 runs in parallel**: don't touch
`gate/rigor_lib/cli.py` or `structure*`.

## Why
annas-c's next module is the `tls_stream` adapter (a `ports_stream_t` on mbedTLS). Its tests need a real TLS
server in-process (handshake success, a wrong host name, an expired certificate, an unknown CA, TLS 1.2 versus 1.3,
truncation, close_notify, an alert mid-stream), deterministic and with no network. Product test authors must not
build or configure crypto, so the peer is gate-owned.

## Allowed paths
`third_party/tls_peer/**` (new), `third_party/selftest/**` (refactor it onto the new peer if that removes
duplication), `third_party/ALLOWED_TEST_LABELS` (new), `gate/rigor_lib/buckfiles.py`,
`gate/rigor_lib/facts_*.py`, `gate/tests/test_buckfiles.py`, `gate/tests/test_facts.py`,
`selftest/third_party.sh`, `docs/third-party.md`.

## Requirements
1. `gate//third_party/tls_peer:tls_peer`: a plain-C, in-memory TLS server API (no sockets) on the renamed
   server copy. It covers start with a chosen identity, put and take bytes, step, established, negotiated
   version, send application data, send close_notify, send a fatal alert, and stop. One peer at a time is fine.
   The header documents everything a test author needs.
2. **Test PKI, gate-owned, checked in as test data**: a root CA, and server identities for `tls.test.invalid`
   that are: valid ECDSA P-256; valid RSA-2048; expired; not yet valid; wrong host name; signed by an unknown CA;
   and a chain with an intermediate. Also the CA PEM for the client side, and a second unrelated CA. Generate them
   once, record exactly how (commands in `docs/third-party.md`), choose validity periods that tests can reach with
   a pinned `mbedtls_platform_set_time` (the client library's time is 0 until set; document the time values
   tests should use), and mark them as throwaway test keys in the header.
3. **Only tests may use it**: buckfiles accepts `gate//third_party/tls_peer:tls_peer` in `deps` only from a
   `c_test` (new allowlist `third_party/ALLOWED_TEST_LABELS`). Any `c_library`/`c_binary` using it is
   `bad-argument`. Its symbols are reserved (`srv_` prefix) and a product defining `srv_*` fails `symbols`.
4. It builds and works in `release` and `san` (the client library is instrumented in san, the peer may stay
   uninstrumented as the T009 server copy is; document it).

## Self-test
Extend `selftest/third_party.sh` with a throwaway product module (client side through the real
`gate//third_party/mbedtls:mbedtls`) and a `c_test` using the peer, covering: a 1.3 and a 1.2 handshake; each
bad identity rejected with the expected verify flags; a client-initiated close; a peer close_notify read as EOF;
truncation without close_notify detected; a peer fatal alert. Red: a `c_library` that depends on the peer fails
`buckfiles`; a product defining `srv_start` fails `symbols`.

## Acceptance
```sh
selftest/third_party.sh
selftest/product_checks.sh
selftest/gate.sh
```
Report: the peer header text, the PKI table (subject, issuer, validity, intended failure), the self-test output in
both modes, and the warm re-run action count.
