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

Files: `third_party/ALLOWED_LABELS` (one exact label per line, currently `gate//third_party/mbedtls:mbedtls`),
`third_party/ALLOWED_TEST_LABELS` (the same, for libraries only a `c_test` may use: currently
`gate//third_party/tls_peer:tls_peer`, see "The TLS test peer" below) and `third_party/RESERVED_PREFIXES`
(`mbedtls_`, `psa_`, `srv_`, `tls_peer_`). All three are strict: no comments, no blank lines, no duplicates,
final newline, regular file; any defect is exit 2. A label may not be on both label lists.

1. **`buckfiles`.** A product `deps` entry is a same-cell label (`:x`, `//pkg:x`) **or an exact string of
   `ALLOWED_LABELS`**. Any other cell-prefixed label (`gate//third_party/curl:curl`, `...:mbedtls_symbols`,
   `@gate//...`, a near miss, and the gate's own targets spelled `//third_party/...`) stays `bad-argument`
   (`why=dep`). A label of `ALLOWED_TEST_LABELS` is accepted from a `c_test` only; from any other macro it is
   `bad-argument` with `why=test-only-dep`. `walk_findings(root, allowed=None, test_allowed=None)` reads the gate's
   own lists by default; `--allowed-labels FILE` and `--allowed-test-labels FILE` override them for tests.
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
wrong sha256, manifest mismatch, missing library facts, and the test-only routes of the next section), then the
library's computed exports (500+ symbols, all `mbedtls_` / `psa_`, none of the features that must be off, exactly
the reviewed libc imports), then a throwaway product (`third_party/tls_peer/selftest/`: the client module
`tls_client.c` and its `c_test` `tls_client_test.c`, both built by the sealed macros) that runs the real
client-only library against the TLS test peer, in `release` and in `san` (ASan + UBSan on the client library).
The two throwaway targets pass both fact gates. The script ends with the number of actions it executed:
0 for every successful build on a warm second run (the builds that must fail are never cached).

## The TLS test peer (T012)

`gate//third_party/tls_peer:tls_peer` is a real TLS server in memory for the tests of a TLS client adapter
(annas-c's `tls_stream`): handshake success, a wrong host name, an expired certificate, an unknown CA, TLS 1.2
versus 1.3, truncation, close_notify, an alert mid-stream, all deterministic and without a network. Product test
authors build and configure no crypto. The API, the time values and the PKI table are in the header
`third_party/tls_peer/tls_peer.h` (it is the documentation a test author reads; plain C types only).

How it is built (`third_party/tls_peer/BUCK`): the pinned mbedTLS tarball a second time with
`srv_config.h` (the gate config plus `MBEDTLS_SSL_SRV_C`), every exported symbol renamed `srv_*` by
`llvm-objcopy --redefine-syms` from the map that `rename.py` derives from that copy's own computed export list,
so both libraries live in one process; the glue `tls_peer.c` (in-memory BIOs, `tls_peer_*` API); and the PKI as
a generated header (`embed_pki.py`, `pki.bzl`: the checked-in `pki/*.pem` files, nothing else, become
`static const char` arrays at build time). The private copy is not sanitizer-instrumented in `san` (two
instrumented copies of one library in a process are an ASan odr-violation by construction); the client library
is. `tls_peer_symbols` is its facts target (kind `c_third_party`, symbols of the glue computed by `llvm-nm`).

### Only tests may use it

1. `buckfiles`: the label is in `third_party/ALLOWED_TEST_LABELS`, accepted in `deps` of a `c_test` only. From a
   `c_library`, `c_binary` or `c_fuzz` it is `bad-argument` (`why=test-only-dep`). Every other target of the
   package (`:mbedtls_srv`, `:srv_archive`, `:srv_lib`, `:tls_peer_symbols`), `@gate//...` and the same-cell
   spelling `//third_party/...` are `bad-argument` (`why=dep`). A dep may not name a `c_test` or what the macro
   derives from it (`_facts`, `_results`, `_coverage`): `bad-argument` (`why=test-target`; matched by package
   and name, so a similar name in the same package is refused, never passed). `alias` and `native.alias` are
   `bad-call` as for any raw rule.
2. `symbols` (the facts gate sees the whole dependency graph): a target whose kind is not `c_test` and that
   reaches a label of `ALLOWED_TEST_LABELS` through any chain of deps, a test target in the chain included, is
   `test-only-dep`, even when its policy entry permits the label. A dep without facts (an alias, a target the
   build did not produce) is `missing-dep-facts`, so a route the gate cannot see is a failure. A test needs
   `third_party = ["gate//third_party/tls_peer:tls_peer"]` in its policy entry like for any library.
3. Reserved names: `srv_` and `tls_peer_` are in `RESERVED_PREFIXES`; a product defining `srv_start`,
   `srv_mbedtls_ssl_read` or `tls_peer_step` fails `symbols` (`symbol-collision`), with or without the peer's
   facts. A product that declares a peer function itself and calls it, hoping a test links the peer, has an
   `undeclared-symbol`. A header-only include does not work either: `tls_peer.h` is visible only to a target
   that names the peer, and it is not passed on through a test; the build fails with "file not found".
4. `facts` takes `--third-party DIR` with all three files (`ALLOWED_TEST_LABELS` is required: a missing file is
   exit 2).

`rigor grade` must build `gate//third_party/tls_peer:tls_peer_symbols` next to `mbedtls_symbols` for a product
whose tests use the peer (T008 owns `grade_*.py`; see "Not wired yet").

### The test PKI

Throwaway test keys, public test data, secure nothing. Generated once by the commands below (OpenSSL 3.0.13) and
checked in as `third_party/tls_peer/pki/*.pem`; the private keys of the CAs were deleted by the script and are
not in the repository. Reference time: `TLS_PEER_TIME_VALID` = 1798761600 = 2027-01-01T00:00:00Z.

| File | Subject (CN) | Issuer (CN) | Valid | Intended failure |
|---|---|---|---|---|
| `root_ca.pem` | c-rigor-gate TLS test root CA (throwaway) | itself | 2020-01-01 to 2126-01-01 | none: the client's trust anchor |
| `other_ca.pem` | c-rigor-gate TLS unrelated test CA (throwaway) | itself | 2020-01-01 to 2126-01-01 | trusting only this: `BADCERT_NOT_TRUSTED` for every identity |
| `ec_valid.*.pem` | tls.test.invalid (ECDSA P-256) | root CA | 2026-01-01 to 2126-01-01 | none |
| `rsa_valid.*.pem` | tls.test.invalid (RSA-2048) | root CA | 2026-01-01 to 2126-01-01 | none |
| `expired.*.pem` | tls.test.invalid (ECDSA) | root CA | 2020-01-01 to 2021-01-01 | `BADCERT_EXPIRED` at `TLS_PEER_TIME_VALID` |
| `not_yet_valid.*.pem` | tls.test.invalid (ECDSA) | root CA | 2100-01-01 to 2126-01-01 | `BADCERT_FUTURE` at `TLS_PEER_TIME_VALID` |
| `wrong_host.*.pem` | wrong-host.test.invalid (ECDSA) | root CA | 2026-01-01 to 2126-01-01 | `BADCERT_CN_MISMATCH` |
| `unknown_ca.*.pem` | tls.test.invalid (ECDSA) | c-rigor-gate TLS hidden signer (throwaway), whose certificate is not published | 2026-01-01 to 2126-01-01 | `BADCERT_NOT_TRUSTED` |
| `chain.*.pem` | tls.test.invalid (ECDSA); `chain.crt.pem` holds the leaf then the intermediate | c-rigor-gate TLS test intermediate CA (throwaway), issued by the root CA, 2020-01-01 to 2126-01-01, pathlen 0 | 2026-01-01 to 2126-01-01 | none (the peer sends the intermediate) |

`*.crt.pem` is the certificate (chain), `*.key.pem` the PKCS#8 private key under a "THROWAWAY TEST KEY" comment
line. Time values for tests (pinned with `mbedtls_platform_set_time`; the client library's time is 0 until set,
so every certificate is "not yet valid" without it): `TLS_PEER_TIME_VALID` (2027-01-01: valid identities in
window, expired and not-yet-valid out), `TLS_PEER_TIME_EXPIRED_WINDOW` (2020-07-01 = 1593561600: the expired
identity is valid), `TLS_PEER_TIME_FUTURE_WINDOW` (2110-01-01 = 4417977600: the not-yet-valid identity is valid).

Commands (`sh genpki.sh third_party/tls_peer/pki`, the script as run, verbatim):

```sh
#!/bin/sh
# Test PKI of the TLS test peer (T012). Run once with OpenSSL 3.0.x:  sh genpki.sh OUTDIR
# Everything is throwaway: the keys are public test data. The CA private keys are deleted at the end.
set -eu
OUT=$1
W=$(mktemp -d)
cd "$W"
mkdir newcerts
cat > ca.cnf <<'CNF'
[ca]
default_ca = ca_default
[ca_default]
database = index.txt
new_certs_dir = newcerts
serial = serial
default_md = sha256
policy = any
unique_subject = no
[any]
commonName = supplied
CNF
cat > ext_ca <<'CNF'
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
CNF
cat > ext_ica <<'CNF'
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
CNF
leaf_ext() { # <dns name>
  printf 'basicConstraints = critical,CA:FALSE\nkeyUsage = critical,digitalSignature\nextendedKeyUsage = serverAuth\nsubjectKeyIdentifier = hash\nauthorityKeyIdentifier = keyid\nsubjectAltName = DNS:%s\n' "$1"
}
SERIAL=1000
# issue <csr> <out.crt> <ca.crt> <ca.key> <ext file> <notBefore> <notAfter> [selfsign]
issue() {
  SERIAL=$((SERIAL + 1))
  : > index.txt
  printf '%04X\n' "$SERIAL" > serial
  if [ "${8:-}" = selfsign ]; then
    openssl ca -batch -config ca.cnf -selfsign -keyfile "$4" -in "$1" -out "$2" -extfile "$5" \
      -startdate "$6" -enddate "$7" -notext
  else
    openssl ca -batch -config ca.cnf -cert "$3" -keyfile "$4" -in "$1" -out "$2" -extfile "$5" \
      -startdate "$6" -enddate "$7" -notext
  fi
}
EC="-newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -pkeyopt ec_param_enc:named_curve"
newkey() { # <name> <subject CN> [rsa]
  if [ "${3:-}" = rsa ]; then
    openssl req -new -nodes -newkey rsa:2048 -keyout "$1.key" -out "$1.csr" -subj "/CN=$2"
  else
    # shellcheck disable=SC2086
    openssl req -new -nodes $EC -keyout "$1.key" -out "$1.csr" -subj "/CN=$2"
  fi
}
V0=20260101000000Z; V1=21260101000000Z   # the usual validity: 2026-01-01 .. 2126-01-01
CA0=20200101000000Z

# --- CAs -------------------------------------------------------------------------------------
newkey root "c-rigor-gate TLS test root CA (throwaway)"
issue root.csr root.crt - root.key ext_ca "$CA0" "$V1" selfsign
newkey other "c-rigor-gate TLS unrelated test CA (throwaway)"
issue other.csr other.crt - other.key ext_ca "$CA0" "$V1" selfsign
newkey hidden "c-rigor-gate TLS hidden signer (throwaway)"
issue hidden.csr hidden.crt - hidden.key ext_ca "$CA0" "$V1" selfsign
newkey inter "c-rigor-gate TLS test intermediate CA (throwaway)"
issue inter.csr inter.crt root.crt root.key ext_ica "$CA0" "$V1"

# --- server identities for tls.test.invalid -----------------------------------------------------
H=tls.test.invalid
newkey ec_valid $H;          leaf_ext $H > e; issue ec_valid.csr ec_valid.crt root.crt root.key e "$V0" "$V1"
newkey rsa_valid $H rsa;     issue rsa_valid.csr rsa_valid.crt root.crt root.key e "$V0" "$V1"
newkey expired $H;           issue expired.csr expired.crt root.crt root.key e 20200101000000Z 20210101000000Z
newkey not_yet_valid $H;     issue not_yet_valid.csr not_yet_valid.crt root.crt root.key e 21000101000000Z "$V1"
newkey wrong_host wrong-host.test.invalid; leaf_ext wrong-host.test.invalid > e2
issue wrong_host.csr wrong_host.crt root.crt root.key e2 "$V0" "$V1"
newkey unknown_ca $H;        issue unknown_ca.csr unknown_ca.crt hidden.crt hidden.key e "$V0" "$V1"
newkey chain $H;             issue chain.csr chain.crt inter.crt inter.key e "$V0" "$V1"
cat chain.crt inter.crt > chain.chain

# --- output: PEM only, keys marked as throwaway ---------------------------------------------------
mkdir -p "$OUT"
note() { printf '# THROWAWAY TEST KEY (c-rigor-gate T012). Public test data, never a secret, never reuse.\n'; }
cp root.crt "$OUT/root_ca.pem"
cp other.crt "$OUT/other_ca.pem"
for n in ec_valid rsa_valid expired not_yet_valid wrong_host unknown_ca; do
  cp "$n.crt" "$OUT/$n.crt.pem"
  { note; openssl pkey -in "$n.key"; } > "$OUT/$n.key.pem"
done
cp chain.chain "$OUT/chain.crt.pem"
{ note; openssl pkey -in chain.key; } > "$OUT/chain.key.pem"
cd /
rm -rf "$W"
```

## How to bump (owner-approved task only)

1. Download the new release tarball from `github.com/Mbed-TLS/mbedtls/releases`, compute its sha256 and size.
2. `python3 -I -B third_party/extract.py --archive T.tar.bz2 --top mbedtls-X.Y.Z --dirs include,library --list`
   and regenerate `third_party/mbedtls/files.bzl` from it; diff the old and new manifest (new files are code the
   gate now trusts).
3. Change `url`, `sha256`, `size_bytes`, `top` in `third_party/mbedtls/BUCK` and in `third_party/tls_peer/BUCK`,
   and the version string in `third_party/tls_peer/selftest/tls_client_test.c` (`pinned_version`).
4. Review the diff of `include/mbedtls/mbedtls_config.h` against `gate_mbedtls_config.h`; fix `check_config.h`
   errors by adding only what the build demands.
5. Run `selftest/third_party.sh`. If the libc import set changes it fails; each new import needs a reviewed reason
   before `REVIEWED_IMPORTS` in the script changes. Record the new numbers in this file.
6. Merge only with the owner's sign-off: `ALLOWED_LABELS` and the pin are what products are allowed to trust.

Adding another library: a `third_party/<name>/BUCK` with `c_third_party(...)`, its label in `ALLOWED_LABELS`, its
prefixes in `RESERVED_PREFIXES`, the same self-test shape, and the same owner sign-off.
