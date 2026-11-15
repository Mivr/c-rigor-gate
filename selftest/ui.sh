#!/usr/bin/env bash
# Self-test of the UI model interface and the probe (U03, P004 4.2): `c_ui_probe` builds the probe binary of a toy LVGL
# app's model adapter in release and san; the scripted sessions in selftest/ui_product (session.in, bad.in) must produce
# the checked-in transcripts byte for byte, twice per mode; and the symbols gate confines the `uim_*` names: the model
# adapter and the probe pass, product code that references or defines one is flagged.
# Needs bash, python3 (stdlib) and tools/buck2. Runs in place on //selftest/ui_product. Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(python3 -I -B gate/rigor)
REL=toolchains//:linux_release
SAN=toolchains//:linux_san
P="//selftest/ui_product"
prod="selftest/ui_product"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
# build_out <var> <platform> <target>: builds the target, sets $var to its output file
build_out() {
  local var="$1" plat="$2" target="$3" log="$out/$step.$RANDOM.log" p; shift 3
  run "$log" build --target-platforms "$plat" "$target" --show-output || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}

begin "c_ui_probe builds the probe of the toy model in release and in san"
build_out probe_rel "$REL" "$P:probe"
build_out probe_san "$SAN" "$P:probe"
echo "  release: $probe_rel"; echo "  san: $probe_san"

# session <binary> <input> <stdout-file>: runs the probe on the input; sets $rc
session() { "$1" < "$2" > "$3" 2> "$3.err"; rc=$?; }

begin "the scripted session is byte-identical to the transcript, twice in each mode, exit 0, nothing on stderr"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  for n in 1 2; do
    session "$bin" "$prod/session.in" "$out/s.$mode.$n"
    [ "$rc" = 0 ] || fail "$CUR: $mode run $n exited $rc" "$out/s.$mode.$n.err"
    [ ! -s "$out/s.$mode.$n.err" ] || fail "$CUR: $mode run $n wrote to stderr" "$out/s.$mode.$n.err"
    cmp -s "$out/s.$mode.$n" "$prod/session.out" || { diff "$prod/session.out" "$out/s.$mode.$n" > "$out/d.txt"; fail "$CUR: $mode run $n differs from session.out" "$out/d.txt"; }
  done
  echo "  $mode: $(wc -l < "$prod/session.out") reply lines, 2 identical runs"
done

begin "a strict protocol: bad, unknown and out-of-order commands get err lines and exit 1 (transcript bad.out), nothing on stderr"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  session "$bin" "$prod/bad.in" "$out/b.$mode"
  [ "$rc" = 1 ] || fail "$CUR: $mode exited $rc, wanted 1" "$out/b.$mode"
  [ ! -s "$out/b.$mode.err" ] || fail "$CUR: $mode wrote to stderr" "$out/b.$mode.err"
  cmp -s "$out/b.$mode" "$prod/bad.out" || { diff "$prod/bad.out" "$out/b.$mode" > "$out/d.txt"; fail "$CUR: $mode differs from bad.out" "$out/d.txt"; }
done
# expect_reply <name> <mode> <wanted last lines (a printf format)> <printf input>: runs the probe on stdin, wants rc 1 and those last lines
expect_tail() {
  local name="$1" bin="$2" want="$3" input="$4" n
  printf "$input" | "$bin" > "$out/t.$name" 2> "$out/t.$name.err"; rc=$?
  [ "$rc" = 1 ] || fail "$CUR: $name: exit $rc, wanted 1" "$out/t.$name"
  [ ! -s "$out/t.$name.err" ] || fail "$CUR: $name wrote to stderr" "$out/t.$name.err"
  n="$(printf "$want" | wc -l)"
  [ "$(tail -n "$n" "$out/t.$name")" = "$(printf "$want" | head -n "$n")" ] || fail "$CUR: $name: wrong replies" "$out/t.$name"
}
for mode in rel san; do
  eval "bin=\$probe_$mode"
  # a last line without newline is not parsed with the leftovers of the previous line
  expect_tail "nonl.$mode" "$bin" 'ok advance 5000\nerr ? malformed\nerr ? eof-without-quit\n' 'open 0 1\nadvance 5000\nadvance 6'
  expect_tail "eof.$mode" "$bin" 'ok open\nerr ? eof-without-quit\n' 'open 0 1\n'
  expect_tail "nul.$mode" "$bin" 'err ? malformed\nok quit\n' 'quit\0junk\nquit\n'
  expect_tail "after.$mode" "$bin" 'ok quit\nerr ? after-quit\n' 'quit\njunk\n'
  head -c 641 /dev/zero | tr '\0' 'a' > "$out/long.in"; printf '\nquit\n' >> "$out/long.in"
  "$bin" < "$out/long.in" > "$out/t.long.$mode" 2>&1; rc=$?
  [ "$rc" = 1 ] && [ "$(sed -n 2p "$out/t.long.$mode")" = "err ? line-too-long" ] && [ "$(tail -1 "$out/t.long.$mode")" = "ok quit" ] || fail "$CUR: long line ($mode): rc=$rc" "$out/t.long.$mode"
  printf 'quit\n\n\n' | "$bin" > "$out/t.quietend.$mode" 2>&1 || fail "$CUR: empty lines after quit must be accepted ($mode)" "$out/t.quietend.$mode"
  # a read error on stdin (a directory) is exit 2, not an end of input
  "$bin" < "$out" > "$out/t.rderr.$mode" 2>&1; rc=$?
  [ "$rc" = 2 ] || fail "$CUR: a read error on stdin must exit 2, got $rc ($mode)" "$out/t.rderr.$mode"
done
echo "  err replies counted; unterminated last line, embedded NUL, input after quit, a 641-byte line: refused, in release and san"

begin "the probe's own unit tests (record grammar, surplus TABs, escapes, flags, frame-seam bytes, strict numbers) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/unit.log" test --target-platforms "$plat" //ui/model:probe_test || fail "$CUR: //ui/model:probe_test failed in $plat" "$out/unit.log"
  grep -Eq "Pass 1\." "$out/unit.log" || fail "$CUR: the test summary in $plat is not a clean pass" "$out/unit.log"
done

begin "a failing model call poisons the session (every later command is not-open until open), a refusal does not"
printf 'open 0 1\napply 3 666 0 -\nsemantic\nopen 0 1\napply 3 99 0 -\nsemantic\nquit\n' | "$probe_san" > "$out/poison.txt" 2>&1
[ "$(sed -n 2,6p "$out/poison.txt" | cut -c1-30)" = "$(printf 'ok open\nfail apply\nerr semantic not-open\nok open\nok apply refused')" ] || fail "$CUR: poison/refusal replies" "$out/poison.txt"

begin "rigor buckfiles accepts the product tree (c_ui_probe, its load, the model header dep)"
"${RIGOR[@]}" buckfiles --root "$prod" --out "$out/bf.json" > "$out/bf.txt" 2>&1 || fail "$CUR: buckfiles refuses $prod" "$out/bf.txt"

begin "the symbols gate reserves the uim_ prefix: the adapter and the probe pass under an unmodified product-style policy (the gate's lvprobe trusted); product code that references or defines one is flagged"
for t in model toy misuse misdef probe; do build_out "f_$t" "$REL" "$P:${t}_facts"; done
build_out f_hdr "$REL" //ui/model:model_facts
build_out f_main "$REL" //ui/model:probe_facts
build_out f_lvp "$REL" //ui/lvprobe:lvprobe_facts
build_out f_lvgl "$REL" //third_party/lvgl:lvgl_symbols
build_out f_ctest "$REL" //ctest:ctest_facts
build_out libc "$REL" toolchains//:libc_symbols
# relabel <src> <dest>: the facts of a product build print the gate's own targets as `gate//...`; this root cell is the gate,
# so `//ui/model:...` and `//ui/lvprobe:...` are rewritten to that spelling (label and deps), the way a product repo's facts read.
relabel() {
  python3 -I - "$1" "$2" <<'PY' || fail "$CUR: relabel $1"
import json, sys
doc = json.load(open(sys.argv[1]))
fix = lambda x: "gate" + x if x.startswith(("//ui/model:", "//ui/lvprobe:")) else x
doc["label"] = fix(doc["label"])
doc["deps"] = sorted(fix(d) for d in doc["deps"])
json.dump(doc, open(sys.argv[2], "w"))
PY
}
# The libc, LVGL and other symbols the probe library really references that no gate dependency defines (not the model's
# `uim_*`, not what the gate's lvprobe exports): from the facts, checked against the checked-in list so that a change of
# the probe's imports is visible in review, and the policy's `allow` is built from it.
relabel "$f_main" "$out/probe_lib.json"
python3 -I - "$out/probe_lib.json" "$f_lvp" > "$out/probe_imports.actual" <<'PY' || fail "$CUR: cannot read the probe library facts"
import json, sys
doc = json.load(open(sys.argv[1]))
lvprobe = {s for u in json.load(open(sys.argv[2]))["units"] for s in u["defined"]}
defined = {s for u in doc["units"] for s in u["defined"]}
undefined = {s for u in doc["units"] for s in u["undefined"]} - defined - lvprobe
print("\n".join(sorted(s for s in undefined if not s.startswith("uim_"))))
PY
cmp -s "$out/probe_imports.actual" "$prod/probe_imports.expected" || { diff "$prod/probe_imports.expected" "$out/probe_imports.actual" > "$out/d.txt"; fail "$CUR: the probe library's imports differ from $prod/probe_imports.expected" "$out/d.txt"; }
python3 -I - "$out" <<'PY' || fail "$CUR: could not write the policy"
import sys
out = sys.argv[1]
UIM = ["uim_instance", "uim_open", "uim_env_inputs", "uim_apply", "uim_settle", "uim_next_due", "uim_step", "uim_frame",
       "uim_semantic", "uim_patches", "uim_domain_count", "uim_domain_at", "uim_trace"]
# The policy of a product: the gate's global block as it is (no uim_ entry of any kind), then the modules.
text = open("policy/hello.toml").read()
head = text.split("[module.")[0]
assert head.count("[global]") == 1 and "uim_" not in head and head.count('trusted = ["//ctest:ctest"]') == 1
# the gate's lvprobe is a gate-owned library like ctest: trusted, its facts given, its exports grant the probe's calls
head = head.replace('trusted = ["//ctest:ctest"]', 'trusted = ["//ctest:ctest", "gate//ui/lvprobe:lvprobe"]')
toy = ["toy_start", "toy_display", "toy_press", "toy_take_press", "toy_show_notice", "toy_hide_notice", "toy_notice_due",
       "toy_step", "toy_node", "toy_notice_shown", "toy_draw"]
probe = ["main", "probe_parse_u64", "probe_parse_i32", "probe_parse_text", "probe_to_hex", "probe_hex_digit",
         "probe_check_records", "probe_advance_to", "probe_reply_err", "probe_reply_plain", "probe_reply_lines",
         "probe_payload", "probe_cmd_frame", "probe_cmd_ink", "probe_cmd_hit_test", "probe_cmd_tap", "probe_cmd_crop",
         "probe_life_line", "probe_why", "probe_fatal", "probe_refuse", "probe_reply_words", "probe_lv_settle",
         "probe_model_settle", "probe_point", "probe_point_err", "probe_node_word",
         "PROBE_SPEC_SEMANTIC", "PROBE_SPEC_PATCHES", "PROBE_SPEC_TRACE"]
libc = open(out + "/probe_imports.actual").read().split()
q = lambda names: "[" + ", ".join('"%s"' % n for n in names) + "]"
mods = """
[module."gate//ui/model:model"]
allow = []
exports = []

[module."gate//ui/model:probe"]
allow = %s
allow_mutable_data = true
exports = %s

[module."//selftest/ui_product:toy"]
third_party = ["gate//third_party/lvgl:lvgl"]
allow = []
allow_mutable_data = true
exports = %s

[module."//selftest/ui_product:model"]
allow = ["snprintf", "memcpy", "memset", "strlen"]
allow_mutable_data = true
exports = %s

[module."//selftest/ui_product:probe"]
allow = []
exports = []
""" % (q(libc), q(probe), q(toy), q(UIM))
case = """
[module."//selftest/ui_product:%s"]
allow = []
exports = %s
"""
open(out + "/policy.good.toml", "w").write(head + mods)
open(out + "/policy.misdef_legacy.toml", "w").write(head + mods + '\n[module."//selftest/ui_product:misdef"]\nallow = []\n')   # no exports key
for name, exports in (("misuse", ["misuse_peek"]), ("misdef", [])):
    open(out + "/policy.%s.toml" % name, "w").write(head + mods + case % (name, q(exports)))
PY
# gate_case <name> <expected exit> <expected finding>... -- <facts name>...: runs the gate on that set of facts
gate_case() {
  local name="$1" want="$2"; shift 2
  local expected=() sets=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do expected+=("$1"); shift; done
  shift
  sets=("$@")
  local fd="$out/fd.$name"; rm -rf "$fd"; mkdir -p "$fd"
  local s src
  for s in "${sets[@]}"; do eval "src=\$f_$s"; relabel "$src" "$fd/$s.json"; done
  "${RIGOR[@]}" facts --gate symbols --facts "$fd" --policy "$out/policy.$name.toml" --libc "$libc" --out "$out/r.$name.json" > "$out/r.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name exited $rc, wanted $want" "$out/r.$name.txt"
  python3 -I - "$out/r.$name.json" "${expected[@]}" <<'PY' || fail "$CUR: $name: findings differ" "$out/r.$name.txt"
import json, sys
doc = json.load(open(sys.argv[1]))
got = sorted("%s:%s" % (f["rule"], f.get("symbol", "")) for f in doc["findings"] if f["severity"] == "error")
want = sorted(sys.argv[2:])
if got != want or (doc["status"] == "PASS") != (not want):
    print("wanted", want, "got", got, doc["status"]); sys.exit(1)
PY
  echo "  $name -> exit $rc ${expected[*]:-}"
}
gate_case good 0 -- hdr main lvgl model toy probe lvp ctest
gate_case misuse 1 "ui-model-symbol:uim_instance" "ui-model-symbol:uim_open" -- hdr main lvgl model toy probe misuse lvp ctest
gate_case misdef 1 "ui-model-symbol:uim_next_due" "unexpected-export:uim_next_due" -- hdr main lvgl model toy probe misdef lvp ctest
# a policy table without an exports key (a legacy table) cannot hide it: the prefix is reserved by the gate itself
cp "$f_misdef" "$out/f_misdef_legacy.json"; f_misdef_legacy="$out/f_misdef_legacy.json"
gate_case misdef_legacy 1 "ui-model-symbol:uim_next_due" -- hdr main lvgl model toy probe misdef_legacy lvp ctest

begin "the lvprobe tests (//ui/lvprobe/...) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/lvprobe.log" test --target-platforms "$plat" //ui/lvprobe/... || fail "$CUR: //ui/lvprobe/... failed in $plat" "$out/lvprobe.log"
  grep -Eq "Pass [1-9][0-9]*\. Fail 0\." "$out/lvprobe.log" || fail "$CUR: the test summary in $plat is not a clean pass" "$out/lvprobe.log"
done

bash selftest/ui_frame.sh || fail "selftest/ui_frame.sh (the probe's frame facts) failed"
echo "ui selftest passed"
