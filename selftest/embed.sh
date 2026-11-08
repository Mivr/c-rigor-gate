#!/usr/bin/env bash
# Self-test of c_embed (T112): a checked-in binary file becomes a const byte array that a c_test reads back in the
# release and san modes, the facts see one const object, and every bad input is refused with a clear message.
# Needs only bash, python3 (stdlib) and tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch_embed"
pkg="//selftest/scratch_embed"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }
# refuses <label> <message fragment>: the target must fail to build and say why
refuses() {
  local log="$out/$step.$1.log" target="$pkg/bad:$1"
  case "$1" in sym_digit|sym_dash|sym_empty|sym_underscore|limit_*|src_*|isdir|missing) target="$pkg/ld_$1:x";; esac
  if run "$log" build --target-platforms "${PLAT}release" "$target"; then fail "$CUR: $1 built" "$log"; fi
  grep -qF -- "$2" "$log" || fail "$CUR: $1 failed for the wrong reason (wanted: $2)" "$log"
  echo "  $1 refused: $2"
}

mkdir -p "$scratch/ok" "$scratch/bad"
cp selftest/embed_product/blob.bin "$scratch/ok/blob.bin"
cat > "$scratch/ok/BUCK" <<'B'
load("@gate//rules:c.bzl", "c_embed", "c_test")

c_embed(name = "blob", src = "blob.bin", symbol = "fx_blob", max_bytes = 64)
c_embed(name = "exact", src = "blob.bin", symbol = "fx_exact", max_bytes = 37)
c_test(name = "blob_test", srcs = ["blob_test.c"], deps = [":blob", ":exact"])

# nul = True (T117): one 0x00 after the data, the length constant unchanged
c_embed(name = "text", src = "text.txt", symbol = "fx_text", max_bytes = 16, nul = True)
c_embed(name = "textplain", src = "text.txt", symbol = "fx_plain", max_bytes = 16)
c_embed(name = "nulblob", src = "blob.bin", symbol = "fx_nulblob", max_bytes = 37, nul = True)
c_test(name = "nul_test", srcs = ["nul_test.c"], deps = [":text", ":textplain", ":nulblob"])
B
printf 'hello' > "$scratch/ok/text.txt"
cat > "$scratch/ok/nul_test.c" <<'C'
#include <stddef.h>
#include <string.h>
#include "ctest/ctest.h"
#include "selftest/scratch_embed/ok/nulblob.h"
#include "selftest/scratch_embed/ok/text.h"
#include "selftest/scratch_embed/ok/textplain.h"

static const unsigned char want[37] = {
    0x00, 0xFF, 0x00, 0x00, 0xFF, 0xFF, 0x0A, 0x22, 0x5C, 0x3F, 0x3F, 0x2F, 0x80, 0x7F, 0x01, 0xFE,
    0x54, 0x54, 0x43, 0x46, 0x00, 0x01, 0x00, 0x00, 0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x00, 0x00, 0xFF,
    0x10, 0x20, 0x30, 0x40, 0x50};

static void t_len_excludes_nul(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)fx_text_len, 5ULL); }
static void t_terminated(ctest_t *t) { CHECK_EQ_U64(t, fx_text[fx_text_len], 0x00ULL); }
static void t_c_string(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)strlen((const char *)fx_text), 5ULL); }
static void t_data_intact(ctest_t *t) { CHECK_EQ_MEM(t, fx_text, fx_text_len, "hello", 5U); }
static void t_binary_terminated(ctest_t *t) {
    CHECK_EQ_MEM(t, fx_nulblob, fx_nulblob_len, want, sizeof(want));
    CHECK_EQ_U64(t, (unsigned long long)fx_nulblob_len, 37ULL);
    CHECK_EQ_U64(t, fx_nulblob[fx_nulblob_len], 0x00ULL);
}
static void t_default_len(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)fx_plain_len, 5ULL); }

CTEST_SUITE("nul", { "len_excludes_nul", t_len_excludes_nul }, { "terminated", t_terminated }, { "c_string", t_c_string },
            { "data_intact", t_data_intact }, { "binary_terminated", t_binary_terminated }, { "default_len", t_default_len })
C
cat > "$scratch/ok/blob_test.c" <<'C'
#include <stddef.h>
#include "ctest/ctest.h"
#include "selftest/scratch_embed/ok/blob.h"
#include "selftest/scratch_embed/ok/exact.h"

static const unsigned char want[37] = {
    0x00, 0xFF, 0x00, 0x00, 0xFF, 0xFF, 0x0A, 0x22, 0x5C, 0x3F, 0x3F, 0x2F, 0x80, 0x7F, 0x01, 0xFE,
    0x54, 0x54, 0x43, 0x46, 0x00, 0x01, 0x00, 0x00, 0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x00, 0x00, 0xFF,
    0x10, 0x20, 0x30, 0x40, 0x50};

static void t_length(ctest_t *t) { CHECK_EQ_U64(t, (unsigned long long)fx_blob_len, 37ULL); }
static void t_bytes(ctest_t *t) { CHECK_EQ_MEM(t, fx_blob, fx_blob_len, want, sizeof(want)); }
static void t_exact_limit(ctest_t *t) { CHECK_EQ_MEM(t, fx_exact, fx_exact_len, want, sizeof(want)); }
static void t_ends(ctest_t *t) { CHECK_EQ_U64(t, fx_blob[0], 0x00ULL); CHECK_EQ_U64(t, fx_blob[fx_blob_len - 1], 0x50ULL); }

CTEST_SUITE("embed", { "length", t_length }, { "bytes", t_bytes }, { "exact_limit", t_exact_limit }, { "ends", t_ends })
C
printf 'x' > "$scratch/bad/one.bin"
: > "$scratch/bad/empty.bin"
head -c 65 /dev/zero > "$scratch/bad/big.bin"
cat > "$scratch/bad/BUCK" <<'B'
load("@gate//rules:c.bzl", "c_embed")

c_embed(name = "empty", src = "empty.bin", symbol = "e1")
c_embed(name = "over", src = "big.bin", symbol = "e2", max_bytes = 64)
c_embed(name = "sym_keyword", src = "one.bin", symbol = "while")
B
# A `fail()` in a macro fails the whole package, so each load-time refusal is a package of its own.
declare -A LOAD_BAD=(
  [sym_digit]='src = "one.bin", symbol = "1abc"'
  [sym_dash]='src = "one.bin", symbol = "a-b"'
  [sym_empty]='src = "one.bin", symbol = ""'
  [sym_underscore]='src = "one.bin", symbol = "_a"'
  [limit_zero]='src = "one.bin", symbol = "e5", max_bytes = 0'
  [limit_huge]='src = "one.bin", symbol = "e6", max_bytes = 16777217'
  [src_label]='src = ":one.bin", symbol = "e7"'
  [src_up]='src = "../bad/one.bin", symbol = "e8"'
  [src_glob]='src = "*.bin", symbol = "e9"'
  [isdir]='src = "dir", symbol = "e3"'
  [missing]='src = "nope.bin", symbol = "e4"'
  [src_abs]='src = "/etc/hostname", symbol = "e10"'
)
for k in "${!LOAD_BAD[@]}"; do
  mkdir -p "$scratch/ld_$k"
  printf 'x' > "$scratch/ld_$k/one.bin"
  [ "$k" != isdir ] || { mkdir "$scratch/ld_$k/dir"; printf x > "$scratch/ld_$k/dir/f"; }
  printf 'load("@gate//rules:c.bzl", "c_embed")\n\nc_embed(name = "x", %s)\n' "${LOAD_BAD[$k]}" > "$scratch/ld_$k/BUCK"
done

begin "buckfiles accepts the fixture packages"
gate/rigor buckfiles --root "$scratch" > "$out/bf.txt" 2>&1 || fail "$CUR" "$out/bf.txt"

for mode in release san; do
  begin "the c_test reads the embedded bytes back in the $mode mode"
  must_pass build --target-platforms "${PLAT}$mode" "$pkg/ok:blob_test_results" --show-output
  res="$(awk '/blob_test_results/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
  [ -f "$res" ] || fail "$CUR: no results file" "$out/$step.log"
  python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
tests, summary = rows[:-1], rows[-1]["summary"]
ids = sorted(r["id"] for r in tests)
assert ids == ["embed/bytes", "embed/ends", "embed/exact_limit", "embed/length"], ids
assert all(r["status"] == "pass" and r["asserts"] > 0 for r in tests), tests
assert summary == {"total": 4, "passed": 4}, summary
' "$res" || fail "$CUR: results are not four passing tests"
  echo "  $mode: 4 tests pass"
done

for mode in release san; do
  begin "nul = True: the array holds the data plus one 0x00, the length excludes it ($mode)"
  must_pass build --target-platforms "${PLAT}$mode" "$pkg/ok:nul_test_results" --show-output
  res="$(awk '/nul_test_results/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
  [ -f "$res" ] || fail "$CUR: no results file" "$out/$step.log"
  python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
tests, summary = rows[:-1], rows[-1]["summary"]
ids = sorted(r["id"] for r in tests)
assert ids == ["nul/binary_terminated", "nul/c_string", "nul/data_intact", "nul/default_len", "nul/len_excludes_nul", "nul/terminated"], ids
assert all(r["status"] == "pass" and r["asserts"] > 0 for r in tests), tests
assert summary == {"total": 6, "passed": 6}, summary
' "$res" || fail "$CUR: results are not six passing tests"
  echo "  $mode: 6 tests pass"
done

begin "the generated source: the default array is the file size, nul = True adds exactly one byte, the length constant is the same"
must_pass build --target-platforms "${PLAT}release" "$pkg/ok:text__gen[c]" "$pkg/ok:textplain__gen[c]" --show-output
src_nul="$(awk '/text__gen/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
src_plain="$(awk '/textplain__gen/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
grep -q 'const unsigned char fx_text\[6\] = {' "$src_nul" || fail "$CUR: nul array is not 6 bytes" "$src_nul"
grep -q 'const unsigned char fx_plain\[5\] = {' "$src_plain" || fail "$CUR: default array is not 5 bytes" "$src_plain"
grep -qx 'const size_t fx_text_len = 5;' "$src_nul" || fail "$CUR: nul length constant" "$src_nul"
grep -qx 'const size_t fx_plain_len = 5;' "$src_plain" || fail "$CUR: default length constant" "$src_plain"

begin "the generated header declares the extern const array and length "
must_pass build --target-platforms "${PLAT}release" "$pkg/ok:blob__gen[h]" --show-output
hdr="$(awk '/blob__gen/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
grep -qx 'extern const unsigned char fx_blob\[\];' "$hdr" || fail "$CUR: array declaration missing" "$hdr"
grep -qx 'extern const size_t fx_blob_len;' "$hdr" || fail "$CUR: length declaration missing" "$hdr"

begin "the facts of the embedded blob exist in both modes and name the library"
must_pass build --target-platforms "${PLAT}release" "$pkg/ok:blob_facts" --show-output
facts="$(awk '/blob_facts/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)"
[ -f "$facts" ] || fail "$CUR: no facts file" "$out/$step.log"
python3 -I -c '
import json, sys
d = json.load(open(sys.argv[1]))
assert d["kind"] == "c_library" and d["label"].endswith(":blob"), d
assert d["deps"] == [], d["deps"]
' "$facts" || fail "$CUR: unexpected facts"
must_pass build --target-platforms "${PLAT}san" "$pkg/ok:blob_facts_san"

begin "every bad input is refused with a clear message"
refuses empty "the file is empty"
refuses over "is over max_bytes 64"
refuses isdir "got a directory"
refuses missing "nope.bin"
refuses sym_digit "must be a C identifier"
refuses sym_dash "must be a C identifier"
refuses sym_empty "must be a C identifier"
refuses sym_underscore "must be a C identifier"
refuses sym_keyword "is a C keyword"
refuses limit_zero "max_bytes"
refuses limit_huge "max_bytes"
refuses src_label "must be one plain file"
refuses src_up "must be one plain file"
refuses src_glob "must be one plain file"
refuses src_abs "must be one plain file"

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
