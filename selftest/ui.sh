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

begin "a strict protocol: bad, unknown and out-of-order commands get err lines and exit 1 (transcript bad.out)"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  session "$bin" "$prod/bad.in" "$out/b.$mode"
  [ "$rc" = 1 ] || fail "$CUR: $mode exited $rc, wanted 1" "$out/b.$mode"
  cmp -s "$out/b.$mode" "$prod/bad.out" || { diff "$prod/bad.out" "$out/b.$mode" > "$out/d.txt"; fail "$CUR: $mode differs from bad.out" "$out/d.txt"; }
done
printf 'open 0 1\n' | "$probe_rel" > "$out/eof.txt" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(tail -1 "$out/eof.txt")" = "err ? eof-without-quit" ] || fail "$CUR: EOF without quit: rc=$rc" "$out/eof.txt"
head -c 600 /dev/zero | tr '\0' 'a' | { cat; printf '\nquit\n'; } | "$probe_rel" > "$out/long.txt" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(sed -n 2p "$out/long.txt")" = "err ? line-too-long" ] && [ "$(tail -1 "$out/long.txt")" = "ok quit" ] || fail "$CUR: long line: rc=$rc" "$out/long.txt"
echo "  err replies counted; EOF without quit and a 600-byte line are refused"

begin "the symbols gate confines uim_*: the model adapter and the probe pass; product code that references or defines one is flagged"
for t in model toy misuse misdef probe; do build_out "f_$t" "$REL" "$P:${t}_facts"; done
build_out f_hdr "$REL" //ui/model:model_facts
build_out f_main "$REL" //ui/model:probe_facts
build_out f_lvgl "$REL" //third_party/lvgl:lvgl_symbols
build_out libc "$REL" toolchains//:libc_symbols
python3 -I - "$out" "$prod" <<'PY' || fail "$CUR: could not write the policy"
import sys
out, prod = sys.argv[1:3]
UIM = ["uim_instance", "uim_open", "uim_env_inputs", "uim_apply", "uim_next_due", "uim_advance", "uim_frame",
       "uim_semantic", "uim_patches", "uim_domain_count", "uim_domain_at", "uim_trace"]
head = open("policy/hello.toml").read().split("[module.")[0]
head = head.replace('trusted = ["//ctest:ctest"]', "trusted = []")
# Every uim_* name is denied everywhere; the one module exempt from that is the probe main, which calls the model.
head = head.replace('"clone", "killpg"', ", ".join('"%s"' % u for u in UIM) + ',\n        "clone", "killpg"')
toy = ["toy_start", "toy_display", "toy_press", "toy_take_press", "toy_show_notice", "toy_hide_notice", "toy_notice_due",
       "toy_step", "toy_title", "toy_button_text", "toy_notice_text", "toy_notice_shown", "toy_draw"]
q = lambda names: "[" + ", ".join('"%s"' % n for n in names) + "]"
mods = '''
[module."//ui/model:model"]
allow = []
exports = []

[module."//ui/model:probe"]
allow = ["fgetc", "fputs", "fputc", "fflush", "snprintf", "strlen", "strcmp", "stdin", "stdout"]
deny_exempt = %s
allow_mutable_data = true
exports = ["main"]

[module."//selftest/ui_product:toy"]
third_party = ["gate//third_party/lvgl:lvgl"]
allow = []
allow_mutable_data = true
exports = %s

[module."//selftest/ui_product:model"]
allow = ["snprintf", "memcpy", "strlen"]
allow_mutable_data = true
exports = %s

[module."//selftest/ui_product:probe"]
allow = []
exports = []
''' % (q(UIM), q(toy), q(UIM))
case = '''
[module."//selftest/ui_product:%s"]
allow = []
exports = %s
'''
open(out + "/policy.good.toml", "w").write(head + mods)
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
  local s
  for s in "${sets[@]}"; do cp "$(eval echo "\$f_$s")" "$fd/$s.json"; done
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
gate_case good 0 -- hdr main lvgl model toy probe
gate_case misuse 1 "denied-symbol:uim_instance" "denied-symbol:uim_open" -- hdr main lvgl model toy probe misuse
gate_case misdef 1 "unexpected-export:uim_next_due" -- hdr main lvgl model toy probe misdef

echo "ui selftest passed"
