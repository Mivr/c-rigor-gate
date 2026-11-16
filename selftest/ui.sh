#!/usr/bin/env bash
# Self-test of the UI model interface and the probe (U03, P004 4.2): `c_ui_probe` builds the probe binary of a toy LVGL
# app's model adapter in release and san; the scripted sessions in selftest/ui_product (session.in, bad.in) must produce
# the checked-in transcripts byte for byte, twice per mode; and the symbols gate confines the `uim_*` names: the model
# adapter and the probe pass, product code that references or defines one is flagged.
# U05: `rigor ui-explore` drives the toy probe (sweep, bfs, walk, replay) with the toy's event catalogue; two deliberately
# broken adapters (probe_nondet, probe_starve), a correct one with a perpetual tick (probe_tick) and a too coarse key give
# their findings (or none), byte-identical across invocations, and each finding replays.
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
  # U24: the toy reports no scene identity: no `identity` in its greeting, the command is refused (counted)
  expect_tail "ident.$mode" "$bin" 'ok open\nerr identity unsupported\nok quit\n' 'open 0 1\nidentity\nquit\n'
  head -c 641 /dev/zero | tr '\0' 'a' > "$out/long.in"; printf '\nquit\n' >> "$out/long.in"
  "$bin" < "$out/long.in" > "$out/t.long.$mode" 2>&1; rc=$?
  [ "$rc" = 1 ] && [ "$(sed -n 2p "$out/t.long.$mode")" = "err ? line-too-long" ] && [ "$(tail -1 "$out/t.long.$mode")" = "ok quit" ] || fail "$CUR: long line ($mode): rc=$rc" "$out/t.long.$mode"
  printf 'quit\n\n\n' | "$bin" > "$out/t.quietend.$mode" 2>&1 || fail "$CUR: empty lines after quit must be accepted ($mode)" "$out/t.quietend.$mode"
  # a read error on stdin (a directory) is exit 2, not an end of input
  "$bin" < "$out" > "$out/t.rderr.$mode" 2>&1; rc=$?
  [ "$rc" = 2 ] || fail "$CUR: a read error on stdin must exit 2, got $rc ($mode)" "$out/t.rderr.$mode"
done
echo "  err replies counted; unterminated last line, embedded NUL, input after quit, a 641-byte line: refused, in release and san"

begin "U24 fix-up 1: a scene identity that breaks the interface (probe_identity_bad, release and san): a node line without identity and a key twice are err identity model-contract, a failing call is fail identity; none poisons (the next identity and next-due still answer)"
build_out probe_idbad_rel "$REL" "$P:probe_identity_bad"
build_out probe_idbad_san "$SAN" "$P:probe_identity_bad"
for mode in rel san; do
  eval "bin=\$probe_idbad_$mode"
  expect_tail "idbad.$mode" "$bin" 'ok open\nerr identity model-contract\nerr identity model-contract\nfail identity\nok identity lines 2\nstate\ttoy\nnode\tbutton\t-\ttoy.press\t0\nok next-due none\nok quit\n' 'open 0 1\nidentity\nidentity\nidentity\nidentity\nnext-due\nquit\n'
  head -1 "$out/t.idbad.$mode" | grep -q ' crop identity$' || fail "$CUR: the greeting does not announce identity ($mode)" "$out/t.idbad.$mode"
done

begin "the probe's own unit tests (record grammar, surplus TABs, escapes, flags, frame-seam bytes, strict numbers) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/unit.log" test --target-platforms "$plat" //ui/model:probe_test || fail "$CUR: //ui/model:probe_test failed in $plat" "$out/unit.log"
  grep -Eq "Pass 1\." "$out/unit.log" || fail "$CUR: the test summary in $plat is not a clean pass" "$out/unit.log"
done

begin "a failing model call poisons the session (every later command is not-open until open), a refusal does not"
printf 'open 0 1\napply 3 666 0 -\nsemantic\nopen 0 1\napply 3 99 0 -\nsemantic\nquit\n' | "$probe_san" > "$out/poison.txt" 2>&1
[ "$(sed -n 2,6p "$out/poison.txt" | cut -c1-30)" = "$(printf 'ok open\nfail apply\nerr semantic not-open\nok open\nok apply refused')" ] || fail "$CUR: poison/refusal replies" "$out/poison.txt"

begin "rigor buckfiles accepts the product tree (c_ui_probe, c_ui_probe_session, their load, the model header dep)"
"${RIGOR[@]}" buckfiles --root "$prod" --out "$out/bf.json" > "$out/bf.txt" 2>&1 || fail "$CUR: buckfiles refuses $prod" "$out/bf.txt"
"${RIGOR[@]}" buckfiles --root selftest/ui_frame_product --out "$out/bf2.json" > "$out/bf2.txt" 2>&1 || fail "$CUR: buckfiles refuses selftest/ui_frame_product" "$out/bf2.txt"

begin "c_ui_probe_session: both toys' session transcripts and the taps session on both toy builds pass as Buck2 tests in release and in san, one result each"
for plat in "$REL" "$SAN"; do
  run "$out/sess.log" test --target-platforms "$plat" "$P:session_test" "$P:pointer_test" "$P:pointer_noentry_test" //selftest/ui_frame_product:session_test || fail "$CUR: the session tests failed in $plat" "$out/sess.log"
  grep -Eq "Pass 4\. Fail 0\." "$out/sess.log" || fail "$CUR: the test summary in $plat is not four passes" "$out/sess.log"
  [ "$(grep -c "c_ui_probe_session root//selftest/ui_\(frame_\)\?product:\(session\|pointer\|pointer_noentry\)_test: PASS" "$out/sess.log")" = 4 ] || fail "$CUR: the session reports in $plat" "$out/sess.log"
  build_out sess_res "$plat" "$P:session_test"
  [ "$(cat "$sess_res")" = "$(printf '{"asserts": 4, "id": "ui_probe_session/selftest.ui_product:session_test", "status": "pass"}\n{"summary": {"passed": 1, "total": 1}}')" ] || fail "$CUR: the results file in $plat" "$sess_res"
done
run "$out/kind.log" uquery "kind(ui_probe_session_run, //selftest/...)" || fail "$CUR: the kind query failed" "$out/kind.log"
[ "$(grep -c '^root//selftest/ui_\(frame_\)\?product:' "$out/kind.log")" = 4 ] || fail "$CUR: kind(ui_probe_session_run) does not list the four sessions" "$out/kind.log"

begin "one changed byte of an expected transcript: buck2 build of the session target still succeeds (the verdict is an artifact), buck2 test FAILS naming the first differing line; the file is restored"
cp "$prod/session.out" "$out/session.out.keep"
trap 'cp "$out/session.out.keep" "$prod/session.out"; rm -rf "$out"' EXIT
python3 -I - "$prod/session.out" <<'PY' || fail "$CUR: could not change the byte"
import sys
data = open(sys.argv[1], "rb").read().split(b"\n")
assert data[4] == b"ok frame lines 27"
data[4] = b"oK frame lines 27"
open(sys.argv[1], "wb").write(b"\n".join(data))
PY
run "$out/flip.build.log" build --target-platforms "$REL" "$P:session_test" || fail "$CUR: the build of the session target failed" "$out/flip.build.log"
if run "$out/flip.test.log" test --target-platforms "$REL" "$P:session_test"; then fail "$CUR: the test passed with a changed byte" "$out/flip.test.log"; fi
grep -qF "stdout line 5 differs: got b'ok frame lines 27\\n', want b'oK frame lines 27\\n'" "$out/flip.test.log" || fail "$CUR: the failure does not name the first differing line" "$out/flip.test.log"
grep -Eq "Pass 0\. Fail 1\." "$out/flip.test.log" || fail "$CUR: the test summary is not one failure" "$out/flip.test.log"
cp "$out/session.out.keep" "$prod/session.out"
trap 'rm -rf "$out"' EXIT
cmp -s "$out/session.out.keep" "$prod/session.out" || fail "$CUR: session.out was not restored"

begin "the symbols gate reserves the uim_, lvprobe_ and lvp_ prefixes: the adapter and the probe pass under an unmodified product-style policy (the gate's lvprobe trusted); product code that references or defines one is flagged"
for t in model toy misuse misdef lvpuse lvpdef probe; do build_out "f_$t" "$REL" "$P:${t}_facts"; done
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
       "uim_semantic", "uim_patches", "uim_domain_count", "uim_domain_at", "uim_trace", "uim_pointer_supported",
       "uim_pointer", "uim_identity_supported", "uim_identity"]   # U24: the two required identity symbols
# The policy of a product: the gate's global block as it is (no uim_ entry of any kind), then the modules.
text = open("policy/hello.toml").read()
head = text.split("[module.")[0]
assert head.count("[global]") == 1 and "uim_" not in head and head.count('trusted = ["//ctest:ctest"]') == 1
# the gate's lvprobe is a gate-owned library like ctest: trusted, its facts given, its exports grant the probe's calls
head = head.replace('trusted = ["//ctest:ctest"]', 'trusted = ["//ctest:ctest", "gate//ui/lvprobe:lvprobe"]')
toy = ["toy_start", "toy_display", "toy_press", "toy_take_press", "toy_show_notice", "toy_hide_notice", "toy_notice_due",
       "toy_step", "toy_node", "toy_notice_shown", "toy_draw", "toy_pointer", "toy_pump", "toy_set_pointer_enabled",
       "toy_pointer_enabled", "toy_set_button_disabled"]
probe = ["main", "probe_parse_u64", "probe_parse_i32", "probe_parse_text", "probe_to_hex", "probe_hex_digit",
         "probe_check_records", "probe_advance_to", "probe_reply_err", "probe_reply_plain", "probe_reply_lines",
         "probe_payload", "probe_cmd_frame", "probe_cmd_ink", "probe_cmd_hit_test", "probe_cmd_tap", "probe_cmd_crop",
         "probe_life_line", "probe_why", "probe_fatal", "probe_refuse", "probe_reply_words", "probe_lv_settle",
         "probe_model_settle", "probe_tick_ok", "probe_point", "probe_point_err", "probe_node_word",
         "probe_cmd_semantic", "probe_cmd_patches", "probe_cmd_trace",
         "probe_cmd_identity", "probe_check_identity", "probe_field_ok",   # U24
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
# the lvprobe prefixes are the gate's whatever a policy allows: the caller's policy even allows the lvprobe name it calls
lvp = """
[module."//selftest/ui_product:%s"]
allow = %s
exports = %s
"""
for name, allow, exports in (("lvpuse", ["lvprobe_count"], ["lvpuse_peek"]), ("lvpdef", [], ["lvp_mine"])):
    open(out + "/policy.%s.toml" % name, "w").write(head + mods + lvp % (name, q(allow), q(exports)))
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
gate_case lvpuse 1 "ui-lvprobe-symbol:lvprobe_count" -- hdr main lvgl model toy probe lvpuse lvp ctest
gate_case lvpdef 1 "ui-lvprobe-symbol:lvp_mine" -- hdr main lvgl model toy probe lvpdef lvp ctest

# ---- U05: rigor ui-explore, the explorer driver ------------------------------------------------------------------------
CAT="$prod/toy.events.toml"
FIX="$prod/fixture.events.toml"
# explore <name> <wanted exit> <probe> <catalogue> <args...>: runs the explorer; findings in $out/x.<name>.json
explore() {
  local name="$1" want="$2" bin="$3" cat="$4"; shift 4
  "${RIGOR[@]}" ui-explore --probe "$bin" --catalogue "$cat" --out "$out/x.$name.json" --summary "$out/x.$name.sum" "$@" \
    > "$out/x.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/x.$name.txt"
  # U05c: every toy probe has the app's own pointer indev; a build without the pointer entry has its taps injected at it,
  # which the run reports once as the info taps-injected (summary taps = indev); the build with the entry never does.
  [ "$want" = 2 ] && return
  local taps=indev; case "$bin" in *probe_pointer) taps=entry;; esac
  python3 -I - "$out/x.$name.json" "$out/x.$name.sum" "$taps" <<'PY' || fail "$CUR: $name: the taps fact and taps-injected" "$out/x.$name.txt"
import json, sys
F = [json.loads(line) for line in open(sys.argv[1])]
S = json.load(open(sys.argv[2]))
injected = [f for f in F if f["check"] == "taps-injected"]
want = [{"taps": "indev", "pointer": False}] if sys.argv[3] == "indev" else []
sys.exit(0 if S["taps"] == sys.argv[3] and [f["observed"] for f in injected] == want
         and all(f["severity"] == "info" and f["path"] == f["path"][:1] for f in injected) else 1)
PY
}
# expect <name> <python expression over F (the findings but taps-injected, which explore checks) and S (the summary)>
expect() {
  python3 -I - "$out/x.$1.json" "$out/x.$1.sum" "$2" <<'PY' || fail "$CUR: $1: wanted $2" "$out/x.$1.txt"
import json, sys
F = [json.loads(line) for line in open(sys.argv[1])]
F = [f for f in F if f["check"] != "taps-injected"]
S = json.load(open(sys.argv[2]))
ids = lambda check: [f["id"] for f in F if f["check"] == check]
all_of = lambda check: [f for f in F if f["check"] == check]
one = lambda check: all_of(check)[0]
sys.exit(0 if eval(sys.argv[3]) else 1)
PY
}
# same <a> <b>: two runs gave byte-identical, non-empty findings files
same() {
  [ -s "$out/x.$1.json" ] || fail "$CUR: $1 has no findings to compare" "$out/x.$1.txt"
  cmp -s "$out/x.$1.json" "$out/x.$2.json" || fail "$CUR: the findings of $1 and $2 differ"
}
# replays <name> <probe> <catalogue>: every finding of run <name> but depth-unsaturated replays from its evidence paths
replays() {
  local name="$1" bin="$2" cat="$3" ident dir n=0
  for ident in $(python3 -I -c 'import json,sys; [print(json.loads(l)["id"].rsplit("/",1)[1]) for l in open(sys.argv[1]) if json.loads(l)["check"] != "depth-unsaturated"]' "$out/x.$name.json"); do
    dir="$out/ev.$name/$ident"
    [ -f "$dir/paths.json" ] || fail "$CUR: $name: no evidence paths for $ident" "$out/x.$name.txt"
    "${RIGOR[@]}" ui-explore --probe "$bin" --catalogue "$cat" --strategy replay --paths "$dir/paths.json" \
      --out "$out/rp.json" > "$out/rp.txt" 2>&1
    [ "$?" -le 1 ] || fail "$CUR: replay of $ident failed" "$out/rp.txt"
    grep -q "/$ident\"" "$out/rp.json" || fail "$CUR: the replay of $name's $ident does not give $ident" "$out/rp.txt"
    n=$((n + 1))
  done
  [ "$n" -gt 0 ] || fail "$CUR: $name has no finding to replay" "$out/x.$name.txt"
  echo "  $n findings of $name replayed to their ids"
}
OPENW="open 1000000000 7"
SEED=(--origin-ms 1000000000 --seed 7)

begin "ui-explore sweep on the toy: C1 = 100 % (both domain entries) evaluated, no finding, byte-identical, release and san"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  explore "sweep.$mode.1" 0 "$bin" "$CAT" --strategy sweep "${SEED[@]}" --require C1
  explore "sweep.$mode.2" 0 "$bin" "$CAT" --strategy sweep "${SEED[@]}" --require C1
  cmp -s "$out/x.sweep.$mode.1.sum" "$out/x.sweep.$mode.2.sum" || fail "$CUR: two sweep summaries ($mode) differ"
  expect "sweep.$mode.1" 'F == [] and S["domain_count"] == 2 and S["domain_visited"] == [0, 1] and S["evaluated"] == ["C1"]'
done

begin "ui-explore bfs on the toy terminates saturated (states per depth, C8 evaluated) and finds the intended F3b canary: in each of the 4 states where the notice shows, its transparent scrim takes the press (tap-press: ok apply missed; probe-press: the scrim, not the lv_button it aims at, takes the tap and nothing changes: tap-misrouted and intent-missed, with the scrim's image), 12 findings that replay; depth 1 is depth-unsaturated; byte-identical twice"
explore bfs.1 1 "$probe_rel" "$CAT" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --require C8 --evidence "$out/ev.bfs.1"
explore bfs.2 1 "$probe_rel" "$CAT" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --require C8 --evidence "$out/ev.bfs.2"
same bfs.1 bfs.2
expect bfs.1 'len(F) == 12 and len(all_of("intent-missed")) == 8 and sorted(f["observed"]["word"] for f in all_of("intent-missed")) == ["probe-press"] * 4 + ["tap-press"] * 4 and all(f["observed"]["applies"] == ["missed"] for f in all_of("intent-missed")) and len({f["state"]["key"] for f in F}) == 4 and len(all_of("tap-misrouted")) == 4 and all(f["observed"] == {"word": "probe-press", "pressed": {"index": 6, "class": "lv_obj", "box": [0, 0, 159, 119]}, "aimed": {"index": 3, "class": "lv_button", "box": [8, 40, 107, 75]}} for f in all_of("tap-misrouted")) and S["outcomes"]["probe-press"] == {"pressed lv_button 8,40,107,75 aimed": 3, "pressed lv_obj 0,0,159,119 other": 4, "tap missed": 4, "tap ok": 3} and S["outcomes"]["probe-blank"] == {"pressed lv_obj 0,0,159,119 root": 3, "pressed lv_obj 0,0,159,119 untargeted": 4, "tap refused": 7} and S["detail"]["states_per_depth"] == [1, 2, 4, 0] and S["abstract_states"] == 7 and S["pairs_exercised"] == 91 and S["evaluated"] == ["C8"] and S["events"]["code-empty"] == {"accepted_states": 0, "refused_states": 7, "missed_states": 0} and S["events"]["tap-press"] == {"accepted_states": 3, "refused_states": 0, "missed_states": 4} and S["events"]["probe-press"] == {"accepted_states": 3, "refused_states": 0, "missed_states": 4} and S["events"]["probe-blank"] == {"accepted_states": 0, "refused_states": 7, "missed_states": 0}'
# the missed and misrouted probe taps carry the PNG of the node that took them (the 160x120 scrim), fetched with crop
python3 -I - "$out/x.bfs.1.json" "$out/ev.bfs.1" <<'PY' || fail "$CUR: the evidence images of the missed taps"
import json, struct, sys, zlib
found = [json.loads(line) for line in open(sys.argv[1])]
taps = [f for f in found if f["observed"].get("word") == "probe-press"]
assert len(taps) == 8 and all(f["id"].rsplit("/", 1)[1] + "/tap-node.png" in f["evidence"] for f in taps)
for f in taps:
    data = open("%s/%s" % (sys.argv[2], f["id"].rsplit("/", 1)[1] + "/tap-node.png"), "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (160, 120)
    raw = zlib.decompress(data[41:-16])
    assert len(raw) == 120 * (1 + 160 * 4) and all(raw[r * 641] == 0 for r in range(120))
assert not any("tap-node.png" in "".join(f["evidence"]) for f in found if f["observed"].get("word") == "tap-press")
PY
replays bfs.1 "$probe_rel" "$CAT"
explore shallow.1 1 "$probe_rel" "$CAT" --strategy bfs "${SEED[@]}" --depth 1 --max-states 100
explore shallow.2 1 "$probe_rel" "$CAT" --strategy bfs "${SEED[@]}" --depth 1 --max-states 100
same shallow.1 shallow.2
expect shallow.1 'len(ids("depth-unsaturated")) == 1 and one("depth-unsaturated")["observed"]["reasons"] == ["last-depth-adds-states"] and one("depth-unsaturated")["observed"]["states_per_depth"] == [1, 2] and len(ids("ui-coverage-gap")) == 26 and len(F) == 27'
echo "  states per depth [1, 2, 4, 0]; 8 intent-missed + 4 tap-misrouted (the scrim canary); depth 1: depth-unsaturated + 26 C8 gaps, byte-identical"

begin "a nondeterministic adapter (pid in the trace) is model-nondeterministic at the press, byte-identical twice, and replays"
build_out probe_nondet "$REL" "$P:probe_nondet"
explore nondet.1 1 "$probe_nondet" "$FIX" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --evidence "$out/ev.nondet.1"
explore nondet.2 1 "$probe_nondet" "$FIX" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --evidence "$out/ev.nondet.2"
same nondet.1 nondet.2
expect nondet.1 'F == all_of("model-nondeterministic") and len(F) == 1 and F[0]["observed"] == {"step": 1, "word": "tap-press", "part": "trace", "item": 0} and F[0]["path"] == ["'"$OPENW"'", "tap-press"]'
replays nondet.1 "$probe_nondet" "$FIX"

begin "an adapter whose deadline never moves gives timer-starvation (33 firings in one 1024 ms window), byte-identical twice, which replays"
build_out probe_starve "$REL" "$P:probe_starve"
explore starve.1 1 "$probe_starve" "$FIX" --strategy bfs "${SEED[@]}" --depth 1 --max-states 100 --evidence "$out/ev.starve.1"
explore starve.2 1 "$probe_starve" "$FIX" --strategy bfs "${SEED[@]}" --depth 1 --max-states 100 --evidence "$out/ev.starve.2"
same starve.1 starve.2
expect starve.1 'len(ids("timer-starvation")) == 1 and one("timer-starvation")["observed"]["firings"] == 33 and one("timer-starvation")["observed"]["limit"] == 32 and one("timer-starvation")["path"][:2] == ["'"$OPENW"'", "tap-press"] and len(ids("ui-coverage-gap")) == 9 and len(ids("depth-unsaturated")) == 1 and len(F) == 11'
replays starve.1 "$probe_starve" "$FIX"

begin "an adapter with a perpetual 250 ms tick: bfs terminates with no finding (settle ends, until-change is one event)"
build_out probe_tick "$REL" "$P:probe_tick"
explore tick 0 "$probe_tick" "$FIX" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --require C8
expect tick 'F == [] and S["detail"]["states_per_depth"][-1] == 0 and S["evaluated"] == ["C8"]'
echo "  states per depth $(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["detail"]["states_per_depth"])' "$out/x.tick.sum")"

begin "a key that omits the label and geometry is key-too-coarse (info) on the toy (beside the scrim canary's 2 intent-missed), and the findings replay"
explore coarse 1 "$probe_rel" "$prod/toy_coarse.events.toml" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --evidence "$out/ev.coarse"
expect coarse 'len(ids("key-too-coarse")) == 2 and len(ids("intent-missed")) == 2 and len(F) == 4 and all(f["severity"] == "info" for f in all_of("key-too-coarse")) and [f["observed"]["witness_path"] for f in F if f["path"] == ["'"$OPENW"'", "env-offline"]] == [["'"$OPENW"'", "tap-press"]]'
replays coarse "$probe_rel" "$prod/toy_coarse.events.toml"

begin "ui-explore walks on the toy (2 seeds x 3 clock origins) find only the scrim canary (intent-missed, tap-misrouted), evaluate nothing, and are byte-identical twice"
explore walk.1 1 "$probe_rel" "$CAT" --strategy walk "${SEED[@]}" --walk-seeds 11,12 --walk-length 12 --extra-origins 2
explore walk.2 1 "$probe_rel" "$CAT" --strategy walk "${SEED[@]}" --walk-seeds 11,12 --walk-length 12 --extra-origins 2
cmp -s "$out/x.walk.1.sum" "$out/x.walk.2.sum" || fail "$CUR: two walk summaries differ"
same walk.1 walk.2
expect walk.1 'len(all_of("intent-missed")) == 2 and len(all_of("tap-misrouted")) == 1 and len(F) == 3 and S["runs"] == 6 and S["evaluated"] == []'
explore walk.req 1 "$probe_rel" "$CAT" --strategy walk "${SEED[@]}" --walk-seeds 11 --walk-length 3 --extra-origins 0 --require C8
expect walk.req 'len(ids("ui-coverage-gap")) == 1 and one("ui-coverage-gap")["observed"] == {"criterion": "C8", "evaluated": False} and len(ids("intent-missed")) == 1 and len(F) == 2'

# ---- U05c: taps through the product's pointer entry -------------------------------------------------------------------
begin "a tap through the toy's pointer entry (probe_pointer: the queue above LVGL) posts touch and the click's press at the tap's instant, pressed and clicked node 3 (the lv_button), the scrim (node 6) under the notice, a blocked tap, the disabled button pressed and not clicked (3 none); the build without the entry (probe) taps at the indev: the same replies, no touch, no pointer capability, taps indev; byte-identical twice in release and san"
build_out probe_ptr_rel "$REL" "$P:probe_pointer"
build_out probe_ptr_san "$SAN" "$P:probe_pointer"
for mode in rel san; do
  for build in ptr ""; do
    eval "bin=\$probe_${build:+${build}_}$mode"
    want="$prod/pointer.out"; kind=entry
    [ -z "$build" ] && { want="$prod/pointer_noentry.out"; kind=noentry; }
    for n in 1 2; do
      session "$bin" "$prod/pointer.in" "$out/pt.$kind.$mode.$n"
      [ "$rc" = 0 ] && [ ! -s "$out/pt.$kind.$mode.$n.err" ] || fail "$CUR: $kind $mode run $n exited $rc" "$out/pt.$kind.$mode.$n"
      cmp -s "$out/pt.$kind.$mode.$n" "$want" || { diff "$want" "$out/pt.$kind.$mode.$n" > "$out/d.txt"; fail "$CUR: $kind $mode run $n differs from $want" "$out/d.txt"; }
    done
    python3 -I "$prod/pointer_check.py" "$kind" "$prod/pointer.in" "$out/pt.$kind.$mode.1" > "$out/ptc.txt" 2>&1 || fail "$CUR: $kind ($mode)" "$out/ptc.txt"
  done
done
echo "  entry: touch + press at 1000 and at 4000, the scrim's tap posts touch only, blocked with touch; no entry: press only"

begin "the pointer path is strict (transcript pointer_bad.out, exit 1, nothing on stderr, release and san): a failing uim_pointer is fail tap and poisons; a product that delivers a second tap is err tap model-contract and poisons; every malformed tap is err tap bad-arguments"
for mode in rel san; do
  eval "bin=\$probe_ptr_$mode"
  session "$bin" "$prod/pointer_bad.in" "$out/pb.$mode"
  [ "$rc" = 1 ] || fail "$CUR: $mode exited $rc, wanted 1" "$out/pb.$mode"
  [ ! -s "$out/pb.$mode.err" ] || fail "$CUR: $mode wrote to stderr" "$out/pb.$mode.err"
  cmp -s "$out/pb.$mode" "$prod/pointer_bad.out" || { diff "$prod/pointer_bad.out" "$out/pb.$mode" > "$out/d.txt"; fail "$CUR: $mode differs from pointer_bad.out" "$out/d.txt"; }
done
[ "$(grep -c '^fail tap$' "$prod/pointer_bad.out")" = 1 ] && [ "$(grep -c '^err tap model-contract$' "$prod/pointer_bad.out")" = 1 ] && [ "$(grep -c '^err \(semantic\|trace\) not-open$' "$prod/pointer_bad.out")" = 2 ] || fail "$CUR: the transcript lacks a failure or its poison" "$prod/pointer_bad.out"

begin "a catalogue that requires pointer (and declares the entry's touch ambient) is refused by the build without the entry (the house message, exit 2) and drives the build with it: bfs saturates and the F3b canary is what the injected build gives, 8 intent-missed (4 probe-press under the scrim, 4 tap-press) and 4 tap-misrouted, no noop-tap-effect (a tap's own touch is not its effect); byte-identical twice, findings replay"
PCAT="$prod/toy_pointer.events.toml"
explore ptr.refused 2 "$probe_rel" "$PCAT" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100
grep -q "the catalogue requires the probe capabilities pointer, which the probe does not announce" "$out/x.ptr.refused.txt" || fail "$CUR: the refusal is not the house message" "$out/x.ptr.refused.txt"
explore ptr.1 1 "$probe_ptr_rel" "$PCAT" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --require C8 --evidence "$out/ev.ptr.1"
explore ptr.2 1 "$probe_ptr_rel" "$PCAT" --strategy bfs "${SEED[@]}" --depth 8 --max-states 100 --require C8 --evidence "$out/ev.ptr.2"
same ptr.1 ptr.2
expect ptr.1 'len(F) == 12 and len(all_of("tap-misrouted")) == 4 and all(f["observed"] == {"word": "probe-press", "pressed": {"index": 6, "class": "lv_obj", "box": [0, 0, 159, 119]}, "aimed": {"index": 3, "class": "lv_button", "box": [8, 40, 107, 75]}} for f in all_of("tap-misrouted")) and sorted(f["observed"]["word"] for f in all_of("intent-missed")) == ["probe-press"] * 4 + ["tap-press"] * 4 and all_of("noop-tap-effect") == [] and all_of("ambient-missing") == [] and all_of("ambient-extra") == [] and S["outcomes"]["probe-press"] == {"pressed lv_button 8,40,107,75 aimed": 3, "pressed lv_obj 0,0,159,119 other": 4, "tap missed": 4, "tap ok": 3} and S["outcomes"]["probe-blank"] == {"pressed lv_obj 0,0,159,119 root": 3, "pressed lv_obj 0,0,159,119 untargeted": 4, "tap refused": 7} and S["detail"]["states_per_depth"] == [1, 2, 4, 0] and S["abstract_states"] == 7 and S["pairs_exercised"] == 91 and S["evaluated"] == ["C8"]'
cmp -s <(python3 -I -c 'import json,sys; print(sorted((f["check"], f["observed"]) for f in map(json.loads, open(sys.argv[1])) if f["check"] != "taps-injected"))' "$out/x.ptr.1.json") <(python3 -I -c 'import json,sys; print(sorted((f["check"], f["observed"]) for f in map(json.loads, open(sys.argv[1])) if f["check"] != "taps-injected"))' "$out/x.bfs.1.json") || fail "$CUR: the canary differs between the two builds"
replays ptr.1 "$probe_ptr_rel" "$PCAT"

begin "the lvprobe tests (//ui/lvprobe/...) pass in release and san"
for plat in "$REL" "$SAN"; do
  run "$out/lvprobe.log" test --target-platforms "$plat" //ui/lvprobe/... || fail "$CUR: //ui/lvprobe/... failed in $plat" "$out/lvprobe.log"
  grep -Eq "Pass [1-9][0-9]*\. Fail 0\." "$out/lvprobe.log" || fail "$CUR: the test summary in $plat is not a clean pass" "$out/lvprobe.log"
done

bash selftest/ui_frame.sh || fail "selftest/ui_frame.sh (the probe's frame facts) failed"
bash selftest/ui_judges.sh || fail "selftest/ui_judges.sh (the ui-scene and ui-fit judges on the canary) failed"
bash selftest/ui_restart.sh || fail "selftest/ui_restart.sh (the declared countdown restart) failed"
bash selftest/ui_taps.sh || fail "selftest/ui_taps.sh (U05e: scene taps, the layer policy, pad map, boot seeds, cost) failed"

begin "no probe process this selftest started is still alive"
build_out canary_rel "$REL" "//selftest/ui_canary_product:probe"   # built by ui_judges.sh: its processes are checked too
build_out canary_san "$SAN" "//selftest/ui_canary_product:probe"
python3 -I - "$root" "$probe_rel" "$probe_san" "$probe_nondet" "$probe_starve" "$probe_tick" "$probe_ptr_rel" "$probe_ptr_san" "$canary_rel" "$canary_san" <<'PY' || fail "$CUR: probe processes left behind"
import os, sys, time
root, binaries = sys.argv[1], {os.path.realpath(os.path.join(sys.argv[1], b)) for b in sys.argv[2:]}
stubs = [os.path.join(root, "gate/tests/data/ui_explore/%s.py" % name).encode() for name in ("stub_probe", "stub_scene")]
def live():
    """Live processes running one of the probe binaries (by /proc/<pid>/exe) or one of the unit tests' stub probes."""
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            state = open("/proc/%s/stat" % pid).read().rsplit(")", 1)[1].split()[0]
            cmd = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
            exe = os.path.realpath("/proc/%s/exe" % pid)
        except OSError:
            continue
        if state != "Z" and (exe in binaries or any(stub in part for part in cmd for stub in stubs)):
            out.append(pid)
    return out
end = time.monotonic() + 5
while live() and time.monotonic() < end:
    time.sleep(0.05)
if live():
    print("alive:", live()); sys.exit(1)
PY
echo "  none"
echo "ui selftest passed"
