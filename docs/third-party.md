# Gate-owned third-party C libraries (T009)

Third-party code cannot meet the product rules (C17 sealed flags, no `malloc`, small files) and must not be
editable by product agents. It lives in the gate under `third_party/`, is pinned by sha256, is built
hermetically on RE with its own flag set, and is reachable from a product only through an exact label.
The first library is mbedTLS 3.6 LTS (TLS for annas-c).

## The pin

| What | Value |
|---|---|
| Release | Mbed TLS **3.6.7** (the newest 3.6.x release when T009 ran) |
| URL | `https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-3.6.7/mbedtls-3.6.7.tar.bz2` |
| sha256 | `a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6` |
| size | 5473689 bytes |

`rules/third_party.bzl` downloads it with `download_file` (sha256 and size checked by Buck2) and unpacks it on
RE with `third_party/extract.py` (Python 3 stdlib `tarfile`, so no `bzip2` binary is needed). Only `include/` and
`library/` are unpacked, only regular files are accepted, and the set of `*.c` / `*.h` files in the archive must
equal `third_party/mbedtls/files.bzl` exactly (an extra or a missing file fails the build). Every file is a
sub-target (`:mbedtls_src[library/aes.c]`), so a compile action has that file as input, never the whole release.

## Targets (`third_party/mbedtls/BUCK`)

| Target | What |
|---|---|
| `gate//third_party/mbedtls:mbedtls` | the static library (the only label a product may name) |
| `:mbedtls_headers` | the public headers and `-DMBEDTLS_CONFIG_FILE=<gate_mbedtls_config.h>`, exported to users with `-isystem` |
| `:mbedtls_src` | the unpacked release |
| `:mbedtls_symbols` | the facts file (kind `c_third_party`), **computed by the build**: `llvm-nm -g` of every object |

Flags of the library itself: mode flags only (`release` `-O2`; `san` and `fuzz` `-O1 -g` plus the sanitizers of
`rules/c.bzl`; `cov` `-O2`, not instrumented) with `-std=c17 -w`. No warning is an error for vendored code, and
none of the sealed product profile applies. The macro `c_third_party` takes no flags from the BUCK file except
the configuration header. Product BUCK files cannot load `rules/third_party.bzl` (`rigor buckfiles`: `bad-load`).

## Configuration (`third_party/mbedtls/gate_mbedtls_config.h`)

Client only. Enabled: TLS 1.2 and 1.3 client (ECDHE-ECDSA, ECDHE-RSA, TLS 1.3 ephemeral, RSA-PSS), X.509
parsing and verification, PEM parsing, secp256r1 / secp384r1 / X25519, RSA (PKCS#1 v1.5 and v2.1), AES-GCM,
ChaCha20-Poly1305, SHA-224/256/384/512, HKDF, CTR_DRBG, the PSA crypto core, SNI, ALPN, extended master
secret, encrypt-then-MAC, `MBEDTLS_PLATFORM_MEMORY` (a product may hand in an arena allocator),
`MBEDTLS_ERROR_C` and `MBEDTLS_VERSION_C` (pure string tables).

Everything else is off, in particular: server, SSLv3 / TLS 1.0 / 1.1, DTLS, renegotiation, session tickets, PSK,
static ECDH, DHE, SHA-1, MD5, CBC / ECB / CTR / CCM, DES, ARIA, Camellia, assembly (`MBEDTLS_HAVE_ASM`,
AES-NI, padlock), sockets (`net_sockets.c` is not even compiled; the product supplies the BIO), `MBEDTLS_FS_IO`,
debug output, threading, the timing module, self tests, PSA storage.

Decisions that go beyond the stock library:

* **Entropy is `getrandom(2)` only.** `MBEDTLS_NO_PLATFORM_ENTROPY` + `MBEDTLS_ENTROPY_HARDWARE_ALT`, and
  `third_party/mbedtls/gate_platform.c` defines `mbedtls_hardware_poll()` (blocking `getrandom`, no fallback). The
  stock source falls back to `/dev/urandom` through `fopen` on `ENOSYS`, which the gate does not want.
* **No ambient clock for certificate validity.** `MBEDTLS_PLATFORM_TIME_ALT` with `MBEDTLS_PLATFORM_STD_TIME`
  set to `mbedtls_gate_time_unset` (always 0). The product injects its clock with `mbedtls_platform_set_time()`;
  until it does, every certificate is "not yet valid" (fail closed). The self-test checks both directions.
* **No `MBEDTLS_FS_IO`.** The task text allowed it "for the CA file loader"; the gate does not enable it at
  all, so the library never opens a file. A product reads its CA bundle through its injected filesystem port and
  passes it to `mbedtls_x509_crt_parse` (PEM, NUL byte included in the length).
* Residual ambient reads that the library keeps, all harmless and visible in the computed export list:
  `clock_gettime` / `time` (relative timers in `mbedtls_ms_time`, used for the PSA RNG personalisation),
  `getpid` (PSA RNG fork protection), `gmtime_r`, `inet_pton` (SAN IP addresses). `selftest/third_party.sh`
  fixes the complete set of libc imports (21 names) and fails when it changes.

A change to this file, to the pin, or to the allowlist is an owner-approved gate change (see below).

## Trust: what the gate does with it

Files: `third_party/ALLOWED_LABELS` (one exact label per line, currently `gate//third_party/mbedtls:mbedtls`)
and `third_party/RESERVED_PREFIXES` (`mbedtls_`, `psa_`). Both are strict: no comments, no blank lines, no
duplicates, final newline, regular file; any defect is exit 2.

1. **`buckfiles`.** A product `deps` entry is a same-cell label (`:x`, `//pkg:x`) **or an exact string of
   `ALLOWED_LABELS`**. Any other cell-prefixed label (`gate//third_party/curl:curl`, `...:mbedtls_symbols`,
   `@gate//...`, a near miss) stays `bad-argument` (`why=dep`). `walk_findings(root, allowed=None)` reads the gate's
   own list by default; `--allowed-labels FILE` overrides it for tests.
2. **`semantic-suppressions`.** A facts file of kind `c_third_party` whose label is on the allowlist is **not
   scanned**. One whose label is not on the allowlist is a finding (`third-party-not-allowed`) and is not trusted.
   Text of the library's headers that ends up in a product unit is still scanned as the product's text (today it
   yields only `__attribute__((mode(TI)))`, which is not forbidden).
3. **`symbols`.** The policy gains `third_party = ["gate//third_party/mbedtls:mbedtls"]` per module (labels must
   be on the allowlist, else exit 2). A module that depends on a library without that entry gets
   `third-party-not-permitted`, and the library's exports do **not** count for it (so its calls are also
   `undeclared-symbol`). With the permission, the exports (computed by the build) count as dependency exports
   (direct deps only, not transitive). A library is not itself checked and cannot be listed as a `[module]`.
   Reserved names: every symbol a trusted library exports **and every external symbol starting with a reserved
   prefix** is a `symbol-collision` when a product defines it, whether or not the product depends on the library.
   `rigor facts --third-party DIR` reads the two lists from `DIR` (default: the gate's `third_party/`).

### Not wired yet (outside T009's paths)

`rigor grade` collects `kind(c_facts, //...)` of the **product** tree. For a product that uses the library the
grade pipeline must additionally build `gate//third_party/mbedtls:mbedtls_symbols` and put its output in the
facts directory (otherwise the `symbols` gate reports `missing-dep-facts` for the dependency: fail closed). That
is `gate/rigor_lib/grade_*.py`, which T008 owns. Defaults of `facts_semantic.run` / `facts_symbols.run` load the
gate's own lists, so the in-process callers in `grade_checks.py` get the new checks without a change. The
product's `products/<p>/policy.toml` needs `third_party = [...]` on the modules that use it.

## Self-test

`selftest/third_party.sh` (RE, run it twice): red cases first (allowlist, permission, collision, reserved prefix,
wrong sha256, manifest mismatch, missing library facts), then the library's computed exports (500+ symbols, all
`mbedtls_` / `psa_`, none of the features that must be off, exactly the reviewed libc imports), then a throwaway
product module (`third_party/selftest/tls_test.c`, built by the sealed `c_test` macro) that does TLS 1.3 (ECDSA
and RSA certificates) and TLS 1.2 handshakes with **the real client-only library** against an in-memory server
over a loopback BIO, checks hostname and CA verification, and checks that the clock must be injected. It runs in
`release` and in `san` (ASan + UBSan on the client library).

The server is `//third_party/selftest:srv`: the same pinned tarball built a second time with
`third_party/selftest/srv_config.h` (the gate config plus `MBEDTLS_SSL_SRV_C`), with every exported symbol
renamed `srv_*` by `llvm-objcopy --redefine-syms` from the map that `rename.py` derives from that copy's own
computed export list, so both libraries live in one process. The private copy is not sanitizer-instrumented (two
instrumented copies of one library in a process are an ASan odr-violation by construction). The test PKI
(`srv_pki.h`: a P-256 CA, an ECDSA and an RSA-2048 server certificate for `tls.selftest.invalid`, valid until
2126) is public test data generated once with OpenSSL.

## How to bump (owner-approved task only)

1. Download the new release tarball from `github.com/Mbed-TLS/mbedtls/releases`, compute its sha256 and size.
2. `python3 -I -B third_party/extract.py --archive T.tar.bz2 --top mbedtls-X.Y.Z --dirs include,library --list`
   and regenerate `third_party/mbedtls/files.bzl` from it; diff the old and new manifest (new files are code the
   gate now trusts).
3. Change `url`, `sha256`, `size_bytes`, `top` in `third_party/mbedtls/BUCK` and in `third_party/selftest/BUCK`,
   and the version string in `third_party/selftest/tls_test.c` (`pinned_version`).
4. Review the diff of `include/mbedtls/mbedtls_config.h` against `gate_mbedtls_config.h`; fix `check_config.h`
   errors by adding only what the build demands.
5. Run `selftest/third_party.sh`. If the libc import set changes it fails; each new import needs a reviewed reason
   before `REVIEWED_IMPORTS` in the script changes. Record the new numbers in this file.
6. Merge only with the owner's sign-off: `ALLOWED_LABELS` and the pin are what products are allowed to trust.

Adding another library: a `third_party/<name>/BUCK` with `c_third_party(...)`, its label in `ALLOWED_LABELS`, its
prefixes in `RESERVED_PREFIXES`, the same self-test shape, and the same owner sign-off.
