#!/usr/bin/env bash
# Self-test of the gate-owned third-party libraries (T009): mbedTLS 3.6 on RE.
#  * red: a dep on any label outside third_party/ALLOWED_LABELS fails `buckfiles`; a module that
#    depends on the library without policy permission fails `symbols`; a module that defines
#    `mbedtls_ssl_read` (or any mbedtls_/psa_ name) fails `symbols` (collision); a wrong sha256 or a
#    tarball whose file set differs from the manifest fails the build;
#  * green: the library's exports are computed by the build (spot checks, and the libc imports are
#    exactly the reviewed set); a permitted module passes both fact gates;
#  * a throwaway product (third_party/selftest/tls_test.c) does TLS 1.3 and TLS 1.2 handshakes with the
#    client-only library against an in-memory server (a renamed private copy of the same release with
#    a server enabled), in `release` and in `san`.
# Needs bash, python3 (stdlib), tools/buck2 and the RE farm. Run it twice: the second run is warm.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
scratch="selftest/scratch_tp"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT
RIGOR=(gate/rigor)
LIB='gate//third_party/mbedtls:mbedtls'

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; T0=$(date +%s); }
took() { echo "  ($(( $(date +%s) - T0 )) s)"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }

cat > "$out/tool.py" <<'PY'
import json, os, re, shutil, sys

def collect(log, dest):
    """copy every `root//<pkg>:<name>_facts|_symbols <path>` of a --show-output log to DEST/<name>.json"""
    os.makedirs(dest, exist_ok=True)
    for line in open(log):
        m = re.match(r"^root//\S+:(\w+?)_(?:facts|symbols)\s+(\S+)$", line.strip())
        if m:
            shutil.copy(m.group(2), os.path.join(dest, m.group(1) + ".json"))

def policy(dest, specs):
    """policy DEST SPEC...  SPEC = name[;third=1]: the global block of hello.toml plus module entries"""
    head = open("policy/hello.toml").read().split("[module.")[0]
    text = head
    for spec in specs:
        name, *opts = spec.split(";")
        text += '[module."//selftest/scratch_tp/p:%s"]\n' % name
        if "third=1" in opts:
            text += 'third_party = ["gate//third_party/mbedtls:mbedtls"]\n'
        text += "\n"
    open(dest, "w").write(text)

def mkfd(allfacts, dest, names):
    os.makedirs(dest, exist_ok=True)
    for name in list(names) + ["ctest"]:
        shutil.copy(os.path.join(allfacts, name + ".json"), os.path.join(dest, name + ".json"))

def check(result, expected):
    doc = json.load(open(result))
    got = sorted(f["rule"] + (":" + (f.get("symbol") or f.get("dep")) if (f.get("symbol") or f.get("dep")) else "")
                 for f in doc["findings"] if f["severity"] == "error")
    want = sorted(expected)
    if got != want:
        print("  wanted %s\n  got    %s" % (want, got)); sys.exit(1)
    if (doc["status"] == "PASS") != (not want):
        print("  status %s does not match findings" % doc["status"]); sys.exit(1)

# The libc/compiler-runtime symbols the pinned configuration may import. A new one means the
# configuration or the release changed and someone must look (docs/third-party.md).
REVIEWED_IMPORTS = {
    "__errno_location", "__udivti3", "bcmp", "calloc", "clock_gettime", "explicit_bzero", "free", "getpid",
    "getrandom", "gmtime_r", "inet_pton", "memchr", "memcpy", "memmove", "memset", "snprintf", "strchr",
    "strcmp", "strlen", "strstr", "time"}
MUST_EXPORT = {"mbedtls_ssl_handshake", "mbedtls_ssl_read", "mbedtls_ssl_write", "mbedtls_x509_crt_verify",
               "mbedtls_x509_crt_parse", "psa_crypto_init", "mbedtls_platform_set_time", "mbedtls_hardware_poll",
               "mbedtls_ctr_drbg_seed", "mbedtls_gate_time_unset"}
MUST_NOT_EXPORT = {"mbedtls_net_connect", "mbedtls_net_send", "mbedtls_ssl_ticket_setup", "mbedtls_ssl_cookie_setup",
                   "mbedtls_ssl_handshake_server_step", "mbedtls_md5", "mbedtls_sha1", "mbedtls_des_crypt_ecb",
                   "mbedtls_dhm_init", "mbedtls_ssl_conf_psk", "mbedtls_timing_get_timer", "mbedtls_debug_print_msg",
                   "mbedtls_x509_crt_parse_file", "mbedtls_pk_parse_keyfile", "mbedtls_x509write_crt_init",
                   "mbedtls_platform_entropy_poll", "mbedtls_aes_crypt_cbc", "mbedtls_camellia_init"}

def exports(path):
    doc = json.load(open(path))
    if doc["kind"] != "c_third_party" or doc["label"] != "//third_party/mbedtls:mbedtls":
        print("  unexpected kind/label %s %s" % (doc["kind"], doc["label"])); sys.exit(1)
    defined = {s for u in doc["units"] for s in u["defined"]}
    undefined = {s for u in doc["units"] for s in u["undefined"]} - defined
    bad = False
    if len(defined) < 500:
        print("  only %d exported symbols" % len(defined)); bad = True
    odd = sorted(s for s in defined if not s.startswith(("mbedtls_", "psa_")))
    if odd:
        print("  exports outside the reserved prefixes: %s" % odd[:10]); bad = True
    if MUST_EXPORT - defined:
        print("  missing exports: %s" % sorted(MUST_EXPORT - defined)); bad = True
    if MUST_NOT_EXPORT & defined:
        print("  exports that the configuration must not build: %s" % sorted(MUST_NOT_EXPORT & defined)); bad = True
    if undefined != REVIEWED_IMPORTS:
        print("  imports differ from the reviewed set: new %s, gone %s"
              % (sorted(undefined - REVIEWED_IMPORTS), sorted(REVIEWED_IMPORTS - undefined))); bad = True
    if any(u["weak"] for u in doc["units"]):
        print("  weak symbols in the library"); bad = True
    print("  %d exported symbols, %d imports" % (len(defined), len(undefined)))
    sys.exit(1 if bad else 0)

def results(path, expected):
    rows = [json.loads(l) for l in open(path)]
    summary = [r for r in rows if "summary" in r]
    tests = {r["id"]: r for r in rows if "id" in r}
    want = {"tls/" + n for n in expected}
    if set(tests) != want:
        print("  tests differ: missing %s, extra %s" % (sorted(want - set(tests)), sorted(set(tests) - want))); sys.exit(1)
    failed = sorted(k for k, r in tests.items() if r["status"] != "pass" or r["asserts"] < 1)
    if failed or len(summary) != 1 or summary[0]["summary"]["passed"] != len(want):
        print("  not all passed: %s" % (failed or summary)); sys.exit(1)
    print("  %d tests passed" % len(want))

COMMANDS = {"collect": lambda a: collect(*a), "policy": lambda a: policy(a[0], a[1:]),
            "mkfd": lambda a: mkfd(a[0], a[1], a[2:]), "check": lambda a: check(a[0], a[1:]),
            "exports": lambda a: exports(a[0]), "results": lambda a: results(a[0], a[1:])}
COMMANDS[sys.argv[1]](sys.argv[2:])
PY
tool() { python3 -I "$out/tool.py" "$@"; }

# --------------------------------------------------------------------------------------
# Throwaway product package. Product build files only call the gate macros.
# --------------------------------------------------------------------------------------
mkdir -p "$scratch/p"
cp third_party/selftest/tls_test.c "$scratch/p/tls_test.c"
cd "$scratch/p" || exit 2
cat > BUCK <<EOF
load("@gate//rules:c.bzl", "c_library", "c_test")

c_test(name = "tls_test", srcs = ["tls_test.c"], deps = ["$LIB", "//third_party/selftest:srv"])
c_library(name = "tp_ok", srcs = ["tp_ok.c"], deps = ["$LIB"])
c_library(name = "tp_noperm", srcs = ["tp_noperm.c"], deps = ["$LIB"])
c_library(name = "tp_collide", srcs = ["tp_collide.c"], deps = ["$LIB"])
c_library(name = "tp_prefix", srcs = ["tp_prefix.c"])
EOF
cat > tp_ok.c <<'EOF'
#include "mbedtls/ssl.h"
#include "psa/crypto.h"
int tp_ok_init(mbedtls_ssl_context *ssl) { mbedtls_ssl_init(ssl); return (int)psa_crypto_init(); }
EOF
sed 's/tp_ok_init/tp_noperm_init/' tp_ok.c > tp_noperm.c
cat > tp_collide.c <<'EOF'
#include <stddef.h>
int mbedtls_ssl_read(void *ssl, unsigned char *buf, size_t len) { (void)ssl; (void)buf; return (int)len; }
EOF
cat > tp_prefix.c <<'EOF'
int psa_fake_helper(void) { return 1; }
EOF
cd "$root" || exit 2

# --------------------------------------------------------------------------------------
begin "buckfiles: only the allowlisted label may be named; every other cell-prefixed dep is refused"
bf() { # <name> <want-exit> <want-why|-> <dep>
  local d="$out/bf/$1"; rm -rf "$d"; mkdir -p "$d"
  printf 'load("@gate//rules:c.bzl", "c_library")\nc_library(name = "a", srcs = ["a.c"], deps = ["%s"])\n' "$4" > "$d/BUCK"
  "${RIGOR[@]}" buckfiles --root "$d" --out "$d/r.json" > "$d/o.txt" 2>&1; local rc=$?
  [ "$rc" = "$2" ] || fail "$CUR: $1 exited $rc, wanted $2" "$d/o.txt"
  if [ "$3" != - ]; then
    python3 -I -c 'import json,sys; f=json.load(open(sys.argv[1]))["findings"]; sys.exit(0 if [(x["rule"],x["why"]) for x in f]==[("bad-argument",sys.argv[2])] else 1)' "$d/r.json" "$3" \
      || fail "$CUR: $1 findings" "$d/r.json"
  fi
  echo "  $1 -> exit $rc"
}
bf curl        1 dep 'gate//third_party/curl:curl'
bf mbed_other  1 dep 'gate//third_party/mbedtls:mbedtls_symbols'
bf mbed_facts  1 dep 'gate//third_party/mbedtls:mbedtls_facts'
bf ctest       1 dep 'gate//ctest:ctest'
bf prelude     1 dep 'prelude//cxx:cxx'
bf at_label    1 dep '@gate//third_party/mbedtls:mbedtls'
bf allowed     0 -   "$LIB"
"${RIGOR[@]}" buckfiles --root "$scratch" > "$out/bf_scratch.txt" 2>&1 || fail "$CUR: the throwaway product's own BUCK" "$out/bf_scratch.txt"

# --------------------------------------------------------------------------------------
begin "build: a wrong sha256 fails, and so does a manifest that differs from the tarball"
mkdir -p "$scratch/bad"
cat > "$scratch/bad/BUCK" <<'EOF'
load("@gate//rules:third_party.bzl", "third_party_tree")
load("//third_party/mbedtls:files.bzl", "MBEDTLS_FILES")

_URL = "https://github.com/Mbed-TLS/mbedtls/releases/download/mbedtls-3.6.7/mbedtls-3.6.7.tar.bz2"

third_party_tree(name = "wrong_sha", url = _URL, size_bytes = 5473689, top = "mbedtls-3.6.7", dirs = ["include", "library"],
                 sha256 = "0000000000000000000000000000000000000000000000000000000000000000", files = MBEDTLS_FILES)
third_party_tree(name = "missing_file", url = _URL, size_bytes = 5473689, top = "mbedtls-3.6.7", dirs = ["include", "library"],
                 sha256 = "a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6",
                 files = [f for f in MBEDTLS_FILES if f != "library/aes.c"])
third_party_tree(name = "extra_file", url = _URL, size_bytes = 5473689, top = "mbedtls-3.6.7", dirs = ["include", "library"],
                 sha256 = "a7e8bcbec0e6f761b4af24f25677626b35f762f68eef79c08677a363212d11f6",
                 files = MBEDTLS_FILES + ["library/not_in_the_release.c"])
EOF
if run "$out/wrong.log" build //selftest/scratch_tp/bad:wrong_sha; then fail "$CUR: a wrong sha256 built" "$out/wrong.log"; fi
grep -qi 'sha256\|digest\|checksum' "$out/wrong.log" || fail "$CUR: wrong sha256 failed for another reason" "$out/wrong.log"
for t in missing_file extra_file; do
  if run "$out/$t.log" build //selftest/scratch_tp/bad:$t; then fail "$CUR: $t built" "$out/$t.log"; fi
  grep -q 'archive and manifest differ' "$out/$t.log" || fail "$CUR: $t failed for another reason" "$out/$t.log"
done
took

# --------------------------------------------------------------------------------------
begin "build (release): the library, its computed exports, and the facts of the throwaway modules"
must_pass build //third_party/mbedtls:mbedtls //third_party/mbedtls:mbedtls_symbols \
  //selftest/scratch_tp/p:tp_ok_facts //selftest/scratch_tp/p:tp_noperm_facts //selftest/scratch_tp/p:tp_collide_facts \
  //selftest/scratch_tp/p:tp_prefix_facts //ctest:ctest_facts toolchains//:libc_symbols --show-output
tool collect "$out/$step.log" "$out/facts" || fail "$CUR: collect"
cp "$(awk '/libc_symbols/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)" "$out/libc.symbols" || fail "$CUR: no libc list"
lib="$(awk '/third_party\/mbedtls:mbedtls / && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
echo "  library: $lib ($(stat -c %s "$lib") bytes)"
took
tool exports "$out/facts/mbedtls.json" || fail "$CUR: exports"

# --------------------------------------------------------------------------------------
gate_case() { # <name> <gate> <want-exit> <policy> <facts>... -- <expected finding>...
  local name="$1" gate="$2" want="$3" pol="$4"; shift 4
  local targets=() expected=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do targets+=("$1"); shift; done
  [ "${1:-}" = "--" ] && shift
  expected=("$@")
  local fd="$out/fd/$name.$gate"; rm -rf "$fd"
  tool mkfd "$out/facts" "$fd" "${targets[@]}" || fail "$CUR: no facts for ${targets[*]}"
  local res="$out/res/$name.$gate.json"; mkdir -p "$out/res"
  "${RIGOR[@]}" facts --gate "$gate" --facts "$fd" --policy "$pol" --libc "$out/libc.symbols" --out "$res" > "$out/res/$name.$gate.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name/$gate exited $rc, wanted $want" "$out/res/$name.$gate.txt"
  tool check "$res" "${expected[@]}" || fail "$CUR: $name/$gate findings differ" "$out/res/$name.$gate.txt"
  echo "  $name/$gate -> exit $rc ${expected[*]:-}"
}
SEM=semantic-suppressions
SYM=symbols
# With the gate as the root cell Buck2 prints the library as //third_party/...
PERM="third-party-not-permitted://third_party/mbedtls:mbedtls"

begin "red: using the library without the policy's permission fails symbols"
tool policy "$out/p_noperm.toml" "tp_noperm"
gate_case noperm $SYM 1 "$out/p_noperm.toml" tp_noperm mbedtls -- \
  "$PERM" "undeclared-symbol:mbedtls_ssl_init" "undeclared-symbol:psa_crypto_init"
begin "red: permission is per module"
tool policy "$out/p_one.toml" "tp_ok;third=1" "tp_noperm"
gate_case one $SYM 1 "$out/p_one.toml" tp_ok tp_noperm mbedtls -- \
  "$PERM" "undeclared-symbol:mbedtls_ssl_init" "undeclared-symbol:psa_crypto_init"

begin "red: defining a symbol the library exports, or any mbedtls_/psa_ name, is a collision"
tool policy "$out/p_collide.toml" "tp_collide;third=1"
gate_case collide $SYM 1 "$out/p_collide.toml" tp_collide mbedtls -- "symbol-collision:mbedtls_ssl_read"
tool policy "$out/p_prefix.toml" "tp_prefix"
gate_case prefix $SYM 1 "$out/p_prefix.toml" tp_prefix -- "symbol-collision:psa_fake_helper"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(1 if any("psa_fake_helper" in u["defined"] for u in d["units"]) else 0)' "$out/facts/mbedtls.json" \
  || fail "$CUR: psa_fake_helper is exported by the library after all"

begin "red: the library's facts missing from the facts directory is a finding, not a pass"
tool policy "$out/p_ok.toml" "tp_ok;third=1"
gate_case nolib $SYM 1 "$out/p_ok.toml" tp_ok -- \
  "missing-dep-facts://third_party/mbedtls:mbedtls" "undeclared-symbol:mbedtls_ssl_init" "undeclared-symbol:psa_crypto_init"

begin "green: a permitted module passes both fact gates (the library is trusted, not scanned)"
gate_case ok $SYM 0 "$out/p_ok.toml" tp_ok mbedtls --
gate_case ok $SEM 0 "$out/p_ok.toml" tp_ok mbedtls --

# --------------------------------------------------------------------------------------
T_LIST=(tls13_ecdsa tls13_rsa tls12_server_only tls12_client_only wrong_host untrusted_ca clock_not_injected clock_injected_late entropy_is_live pinned_version)

begin "TLS 1.3 / 1.2 handshakes against the in-memory server, release"
must_pass build //selftest/scratch_tp/p:tls_test_results --show-output
res="$(awk '/tls_test_results/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
tool results "$res" "${T_LIST[@]}" || fail "$CUR: results" "$res"
took

begin "TLS 1.3 / 1.2 handshakes against the in-memory server, san (ASan + UBSan on the client library)"
must_pass build --target-platforms toolchains//:linux_san //selftest/scratch_tp/p:tls_test_results --show-output
res="$(awk '/tls_test_results/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
tool results "$res" "${T_LIST[@]}" || fail "$CUR: results" "$res"
took

echo "selftest/third_party.sh: all steps passed"
