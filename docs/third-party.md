# Gate-owned third-party C libraries (T009)

Third-party code cannot meet the product rules (C17 sealed flags, no `malloc`, small files) and must not be
editable by product agents. It lives in the gate under `third_party/`, is pinned by sha256, is built
hermetically on RE with its own flag set, and is reachable from a product only through an exact label.
The first library is mbedTLS 3.6 LTS (TLS for annas-c); the second is LVGL 9.6.0 (the lockers/stock UI, see "LVGL" below).

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

Files: `third_party/ALLOWED_LABELS` (one exact label per line, currently `gate//third_party/mbedtls:mbedtls` and
`gate//third_party/lvgl:lvgl`),
`third_party/ALLOWED_TEST_LABELS` (the same, for libraries only a `c_test` may use: currently
`gate//third_party/tls_peer:tls_peer`, see "The TLS test peer" below) and `third_party/RESERVED_PREFIXES`
(`mbedtls_`, `psa_`, `srv_`, `tls_peer_`, `lv_`, `LV_`, `lvgl_`). All three are strict: no comments, no blank lines, no duplicates,
final newline, regular file; any defect is exit 2. A label may not be on both label lists.

1. **`buckfiles`.** A product `deps` entry is a same-cell label (`:x`, `//pkg:x`) **or an exact string of
   `ALLOWED_LABELS`**. Any other cell-prefixed label (`gate//third_party/curl:curl`, `...:mbedtls_symbols`,
   `@gate//...`, a near miss, and the gate's own targets spelled `//third_party/...`) stays `bad-argument`
   (`why=dep`). A label of `ALLOWED_TEST_LABELS` is accepted from a `c_test` only; from any other macro it is
   `bad-argument` with `why=test-only-dep`. `walk_findings(root, allowed=None, test_allowed=None)` reads the gate's
   own lists by default; `--allowed-labels FILE` and `--allowed-test-labels FILE` override them for tests.
2. **`semantic-suppressions`.** A facts file of kind `c_third_party` whose label is on the allowlist is **not
   scanned**. One whose label is not on the allowlist is a finding (`third-party-not-allowed`) and is not trusted.
   Text of the library's headers that ends up in a product unit is **not** the product's text (T108): the facts
   rule (`rules/facts.bzl`) passes `--vendor-marker /art/<gate cell>/third_party/` to the scanner (the fragment
   `c_structure` already uses), and a file whose path contains it is skipped like a file below a `--system-root`.
   A product `#define`/`#undef` of a name such a header also defines stays `reserved-macro`, so a product cannot
   redefine `LV_*` or `MBEDTLS_*` behind the library's back. A product directory named `third_party` is another
   cell/path and is not exempt; without the marker nothing changes (fail closed).
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

## How to bump mbedTLS (owner-approved task only)

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

## LVGL 9.6.0 (T107)

The UI library of business-apps (lockers kiosk, later stock; design D7). Only `lib/ui/uikit` and `lib/ui/lvrender`
may include it. Software renderer, a pool the product owns, no OS, no libc allocation.

### The pin

| What | Value |
|---|---|
| Release | LVGL **9.6.0** |
| URL | `https://github.com/lvgl/lvgl/archive/refs/tags/v9.6.0.tar.gz` |
| sha256 | `b20ee3acc1bba13c62d854f9ebd62e4c51e0b443b1e0225892e86442defa84df` |
| size | 111467067 bytes |
| top | `lvgl-9.6.0` |

Unpacked like mbedTLS (`third_party/extract.py`, no change to it): `--dirs src,include,lvgl.h,lvgl_private.h,lv_version.h`
(a directory entry matches by prefix, a file entry by equality). The `*.c` / `*.h` set of those must equal
`third_party/lvgl/files.bzl` (1291 files) exactly.

### Targets (`third_party/lvgl/BUCK`)

Same four as mbedTLS: `gate//third_party/lvgl:lvgl` (the only label a product may name), `:lvgl_headers` (exported
`-isystem`, with `-DLV_CONF_PATH=<gate_lv_conf.h>`), `:lvgl_src`, `:lvgl_symbols` (facts, computed by `llvm-nm`).
A product writes `#include "lvgl.h"` and `#include "lvgl_gate.h"` (the gate's pool and test-display glue). The public
headers keep their layout (`include/lvgl/...`, plus the three top-level headers); `rules/third_party.bzl` gained two
optional arguments for this, `public_header_map` and `tree_input`, which default to the mbedTLS behaviour.

Why `tree_input`: LVGL's sources include each other by relative path (`../misc/lv_event_private.h`), so a compile
action cannot get single files as input. Every LVGL compile action gets the whole unpacked tree (`-I$(location
:lvgl_src)`); the tree is one cached artifact, and a change of the pin invalidates everything anyway.

### Configuration (`third_party/lvgl/gate_lv_conf.h`)

Every option that must be off is set to 0 in the file; the rest takes the library's defaults.

* **Memory.** `LV_USE_STDLIB_MALLOC = LV_STDLIB_BUILTIN` (LVGL's TLSF allocator), builtin string and sprintf. No pool
  inside the library: `LV_MEM_POOL_ALLOC` / `LV_MEM_POOL_INCLUDE` make `lv_init()` take its pool from
  `lvgl_gate_pool_take()`. The product hands it in with **`lvgl_gate_set_pool(mem, LV_MEM_SIZE)` before `lv_init()`**
  (again before every later `lv_init()`): `mem` 8-byte aligned, exactly `LV_MEM_SIZE` bytes = 512 KiB. A missing,
  misaligned or wrong-sized pool traps. 512 KiB is the allocator's compile-time ceiling (`TLSF_MAX_POOL_SIZE` is
  `LV_MEM_SIZE`), so it is both the size handed in and the maximum; `lv_mem_add_pool()` stays available for more.
  Allocation past the pool: `lv_malloc()` returns NULL (self-test). An internal allocation that fails is
  `LV_ASSERT_MALLOC` and traps instead of dereferencing NULL. No libc `malloc`, `calloc`, `realloc` or
  `free` appears in the compiled objects (the self-test checks the import set).
* **No OS.** `LV_USE_OS = LV_OS_NONE`: LVGL runs only on the product's UI thread; no threads, no `pthread`, no locks.
* **Rendering.** `LV_USE_DRAW_SW` only, `LV_COLOR_FORMAT_DEFAULT = LV_COLOR_FORMAT_XRGB8888` (32 bit; the 9.6.0 name
  for `LV_COLOR_DEPTH 32`). Blend targets compiled: XRGB8888 / ARGB8888 (one file `blend_to_rgb888.c` serves
  XRGB8888) and A8. Off: RGB565 and its swapped form, RGB888, L8, AL88, I1, premultiplied ARGB, vector graphics,
  ThorVG, matrices, float, snapshots, assembler / Helium / Neon paths, and every GPU or other draw unit (VG-Lite,
  Dave2D, PXP, PPA, DMA2D, EVE, SIFLI, G2D, NEMA, NanoVG, OpenGL ES, SDL).
* **No logging, assertions that stop.** `LV_USE_LOG 0`. `LV_ASSERT_HANDLER` is `__builtin_trap();` (the process
  dies at once; the stock handler `while(1);` would spin forever). Enabled: malloc and NULL asserts; off: style,
  object and memory-integrity asserts.
* **No files.** All `LV_USE_FS_*` 0 (`src/fs/lv_fs.c`, the driver-less abstraction, is compiled because the image
  decoder links it; it opens nothing), no PNG / BMP / JPEG / WebP / GIF / SVG / FFmpeg / lottie decoders, no
  screenshot compare (needs a file system and PNG). `lv_tiny_ttf_create_file*` is not built
  (`LV_TINY_TTF_FILE_SUPPORT 0`).
* **Widgets.** obj (core), label, button, image, plus flex and grid layouts and the default theme. Off: every other
  widget (animimg, arc, arclabel, bar, buttonmatrix, calendar, canvas, chart, checkbox, dropdown, imagebutton, keyboard,
  led, line, list, menu, msgbox, roller, scale, slider, span, spinbox, spinner, switch, textarea, table, tabview,
  tileview, win), the simple and mono themes, observers, object properties / names / ids, translations,
  gridnav, gestures, BiDi and Arabic shaping, the font manager, imgfont, FreeType, compressed fonts.
* **Fonts.** Built-in: Montserrat 14 only (Latin, digits, symbols; it has no Cyrillic). The kiosk is Bulgarian by
  default, so **Tiny TTF is on** (`LV_USE_TINY_TTF 1`, `LV_TINY_TTF_CACHE_GLYPH_CNT 128`, kerning cache 256): a
  product ships a TTF and loads it from memory with `lv_tiny_ttf_create_data()`; its glyph cache and rasteriser
  allocate from the pool. **No font is vendored in this task** (follow-up: choose and pin a Cyrillic TTF, with its
  licence, for business-apps). stb_truetype's `floor` / `ceil` would call `floorf` / `ceilf` of libm, which products
  do not link; the config defines integer `STBTT_ifloor` / `STBTT_iceil` instead.
* **Test display and test input.** `LV_USE_TEST 1`: `lv_test_indev_*` (simulated mouse, keypad, encoder: press,
  release, `lv_test_mouse_click_at`) and `lv_test_wait` / `lv_test_fast_forward` (advance the LVGL tick and run timers,
  no clock involved). `lv_test_display_create()` is **not compiled**: it calls libc `malloc` / `free`. The gate's
  `lvgl_gate_test_display_create(w, h, buf, bytes, draw_buf)` replaces it: a full-frame XRGB8888 display on a buffer
  the test owns (`LVGL_GATE_TEST_BUF_BYTES(w, h)` bytes) and a flush that completes at once;
  `lvgl_gate_test_display_pixel(draw_buf, x, y)` reads a pixel as `0x00RRGGBB`. Products compare pixels or a CRC
  they compute themselves; the object tree is walked with `lv_obj_get_child_count()` / `lv_obj_get_child()`.
  Also not compiled: `lv_test_fs`, `lv_test_screenshot_compare`, the EGL test display.

Not compiled, per directory of `src/` (its files are in the manifest and so unpacked, but never built):

| Directory | Why not |
|---|---|
| `drivers/` | display, input and window-system ports (SDL, X11, Wayland, evdev, libinput, fbdev, DRM, NuttX, QNX, UEFI, Windows, OpenGL ES); the product supplies its own flush and input callbacks |
| `draw/{vg_lite,nxp,renesas,espressif,sifli,nema_gfx,eve,nanovg,dma2d,opengles,sdl}`, `libs/vg_lite_driver`, `libs/nanovg` | other draw backends and GPU drivers |
| `draw/sw/lv_draw_sw_vector.c`, `draw/lv_draw_vector.c`, `draw/lv_draw_3d.c`, `draw/snapshot`, `libs/thorvg`, `libs/gltf`, `image/svg` | vector graphics, 3D, SVG, snapshots |
| `draw/sw/blend/{rgb565*,l8,al88,i1,argb8888_premultiplied}`, `blend/{neon,helium,riscv_v,sve2,arm2d}` | colour formats and assembler paths that are off |
| `osal/` (all but `lv_os.c`, `lv_os_none.c`) | pthread, FreeRTOS, CMSIS, RT-Thread, Windows, SDL2, Linux, MQX ports |
| `stdlib/{clib,micropython,rtthread,uefi}` | other allocators and string libraries |
| `fs`, `libs/{fsdrv,frogfs}` (all but `lv_fs.c`) | file system drivers |
| `libs/` (png, jpeg, webp, bmp, gif, lodepng, tjpgd, ffmpeg, gstreamer, freetype, barcode, qrcode, rlottie, lz4, rle) | file-based or third-party decoders and codecs |
| `font/{freetype,imgfont,font_manager,binfont_loader}`, the other built-in fonts | not needed or needing files |
| `widgets/*` except label, button, image; `others/`; `themes/{simple,mono}`; `debugging/{sysmon,profiler,monkey,vg_lite_tvg}`; `logging/` | features that are off |
| `misc/{lv_templ,lv_tree,lv_bidi,lv_text_ap,lv_matrix}.c`, `core/{lv_observer,lv_obj_property,lv_obj_id_builtin}.c`, `indev/{lv_gridnav,lv_indev_gesture}.c` | features that are off |

### Self-test

`selftest/third_party.sh` gained the LVGL steps (the same shape as mbedTLS): the allowlist spellings (`:lvgl` accepted,
`:lvgl_symbols`, `:lvgl_src`, `:lvgl_headers`, `:lvgl_facts`, the same-cell spelling refused), the computed exports (all
`lv_` / `lvgl_`, the must-export and must-not-export lists, no weak symbols), **exactly three libc imports**
(`memcpy`, `memset`: struct copies the compiler lowers to calls; `__assert_fail`: `assert()` in stb_truetype on a corrupt
font; no `malloc` / `calloc` / `realloc` / `free`, no `pthread_*`, no file, socket or clock call), the permission,
collision (`lv_malloc`, `lv_fake_helper`) and missing-facts red cases, and a throwaway c_test
(`selftest/third_party/lvgl/lvgl_ui_test.c`) built in `release` and in `san` (ASan + UBSan on the library). The test
hands in a 512 KiB pool, creates a 320x240 memory display, draws a label and a button (pixel checks, a frame CRC that
is stable across redraws and changes with the text), clicks the button with the simulated mouse and sees its
`LV_EVENT_CLICKED` callback (a click outside does nothing), deletes the scene repeatedly and checks that the bytes
in use and the number of live allocations return to the same values, checks that `lv_malloc()` of 512 KiB, of 1 TiB
and of the 5th 64 KiB chunk return NULL without aborting and that the pool works again after `lv_free`, and that
`lv_tiny_ttf_create_data()` refuses garbage without leaking.

`san` finding: `lv_deinit()` with a display still alive trips `-fsanitize=function` (LVGL deletes displays through a
`void (*)(void *)` pointer to `lv_display_delete`). Delete displays and input devices first, then `lv_deinit()`; the
self-test does.
(Since T114 the library is built without that one check, see the next section; the self-test keeps the order.)

### `-fno-sanitize=function` for LVGL only (T114)

Cause. LVGL stores callbacks of a specific prototype in generic-prototype slots and calls them through the generic
type. Tiny TTF's glyph cache (`src/font/tiny_ttf/lv_tiny_ttf.c:441-463`, `lv_tiny_ttf_cache_create`) installs
`(lv_cache_create_cb_t)tiny_ttf_glyph_cache_create_cb` and the free / compare callbacks the same way. `lv_cache_acquire_or_create`
(`src/misc/cache/lv_cache.c:179`) calls `cache->ops.create_cb(...)` through
`bool (*)(void *node, void *user_data)` (`lv_cache_create_cb_t`, `lv_cache.h:47`), while the function that runs is
`static bool tiny_ttf_glyph_cache_create_cb(tiny_ttf_glyph_cache_data_t *node, void *user_data)` (`lv_tiny_ttf.c:574`).
`-fsanitize=function` compares the two prototypes at the indirect call: "call to function
tiny_ttf_glyph_cache_create_cb through pointer to incorrect function type 'bool (*)(void *, void *)'". The same
pattern is in the font / image caches and in `lv_deinit` (above). The gate's own glue (`lvgl_gate.c`, `gate_lv_conf.h`)
installs none of these callbacks, so it is not the cause (option a does not apply); the gate has no mechanism to
apply a reviewed patch to the pinned tarball and this task does not invent one (option b does not apply).

Fix. `c_third_party(..., no_sanitize = ["function"])` adds `-fno-sanitize=function` to the LVGL library's own compile
flags in the `san` and `fuzz` modes, nothing else: every other check (address, the other undefined-behaviour checks,
leak) stays on for LVGL, the flag is not exported to users, and no other library (mbedTLS, the TLS peer) has it. The
check is performed at the calling side, and the offending call sites are all inside LVGL. Why it is harmless on the
gate's ABIs (x86-64 and AArch64 System V / AAPCS64, the only targets): the real and the generic prototype differ only in
the pointee type of a data-pointer parameter, which has the same size, class and register as `void *`; the call
therefore behaves exactly as with the right type, and a release build already runs this code.

Evidence (`selftest/third_party.sh`). The test `tiny_ttf_glyphs_and_label_from_memory` in `lvgl_ui_test.c` loads a TTF
from memory (`c_embed` of `selftest/third_party/lvgl/font/box.ttf`: three glyphs, 'A', 'B' and U+0411, generated by
`font/mkttf.py` from nothing, CC0, `font/LICENSE.txt`), reads glyph descriptors and draws a label. Before the flag it
passes in release and aborts in san with the message above; after, it passes in both. Canary: `fn_canary.c` is product
code that calls `fnc_twice(int *)` through an `int (*)(void *)` pointer; it passes in release and in san is still aborted
by `-fsanitize=function` ("incorrect function type", naming `fnc_twice`), so product code keeps the check.

**Headers are not product text (T108).** The LVGL headers define identifiers `semantic-suppressions` reserves
(`_LV_CONCAT`, `_PARA`, `_LV_EVENT_LAST`, `_LV_FLEX_*`, `_LV_LL_READ*`, the `__LV_UEFI_*_H__` include guards): 15
`reserved-macro` findings in any unit that includes `lvgl.h` until T108. Text in a gate-owned third-party header tree
is now skipped exactly like toolchain-header text (see "`semantic-suppressions`" above and `docs/product-checks.md`).
The self-test has a green case (a unit including `lvgl.h`, and the throwaway test, pass) and red cases (`#undef
LV_COLOR_DEPTH`, or `#undef` + `#define _LV_CONCAT`, after `lvgl.h`: `reserved-macro`). The `symbols` gate is green.
`RESERVED_PREFIXES` has `lv_`, `LV_`, `lvgl_`; `_lv_` (the task listed it) does not match the loader's prefix
pattern (`[A-Za-z]...`), and no exported symbol starts with it.

Note for later: LVGL event callbacks (`lv_obj_add_event_cb`) are callback registrations into third-party code; T106
makes `indirect-cycle-possible` precise for gate-owned libraries.

### Numbers (release, measured by the self-test)

| What | Value |
|---|---|
| Files in the manifest | 1291 (`src/` + `include/` + 3 top-level headers) |
| Compiled units | 99 (98 LVGL sources + `lvgl_gate.c`) |
| Library (`liblvgl.a`, release) | about 1.0 MB (1021350 bytes) |
| Exported symbols | 1700 (`lv_` and `lvgl_`) |
| libc imports | 3 (`__assert_fail`, `memcpy`, `memset`) |
| Pool peak of the self-test scene (`lv_mem_monitor`, `max_used`) | 9288 bytes of 524288 |
| Pool in use after the scene is built, rendered, clicked and deleted | 6136 bytes (state LVGL keeps: timers, caches) |
| Cold build of the library and its facts on RE | about 86 s (97 actions) |

### How to bump (owner-approved task only)

1. Download the new release tarball, compute sha256 and size; read the release notes for removed or renamed options.
2. `python3 -I -B third_party/extract.py --archive T.tar.gz --top lvgl-X.Y.Z --dirs src,include,lvgl.h,lvgl_private.h,lv_version.h --list`
   and regenerate `third_party/lvgl/files.bzl`; diff the manifests (new files are code the gate now trusts).
3. Change `url`, `sha256`, `size_bytes`, `top` in `third_party/lvgl/BUCK`; adjust the `srcs` lists for renamed files.
4. Compare `lv_conf_template.h` of the new release with `gate_lv_conf.h`; a new option that defaults to on and
   pulls in files, drivers or libc calls must be set to 0 explicitly. `lv_conf_internal.h` shows the defaults.
5. Run `selftest/third_party.sh`; a changed libc import set fails it, each new import needs a reviewed reason before
   `LV_REVIEWED_IMPORTS` changes. Record the new numbers above.
6. Merge only with the owner's sign-off.
