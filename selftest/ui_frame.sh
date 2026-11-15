#!/usr/bin/env bash
# Self-test of the probe's frame facts (U05a, docs/ui-model.md "Frame facts"), called by selftest/ui.sh: the frame toy in
# selftest/ui_frame_product is built as a probe in release and san; its scripted sessions (session.in, bad.in) must give
# the checked-in transcripts byte for byte, twice per mode; and the facts the transcript holds are checked one by one
# by selftest/ui_frame_product/check.py (node coords, label texts with Bulgarian, `clipped` with and without room, the hit
# query firing nothing, the tap and `ok apply missed` under the overlay, the queued work a tap and an animation leave run
# at their time, ink 0 of a hidden label and a frame ink does not change, lifecycle lines, a frame over the budget and
# every broken model interface as typed errors, crop pixels and its payload bound, a frame that changes no timing).
# Needs bash, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
REL=toolchains//:linux_release
SAN=toolchains//:linux_san
P="//selftest/ui_frame_product"
prod="selftest/ui_frame_product"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

step=0
fail() { echo "FAIL [frame $step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[frame $step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
build_out() {
  local var="$1" plat="$2" target="$3" log="$out/$step.$RANDOM.log" p
  "${B[@]}" build --target-platforms "$plat" "$target" --show-output 2>&1 | strip_ansi > "$log"
  [ "${PIPESTATUS[0]}" = 0 ] || fail "$CUR: build $target failed" "$log"
  p="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
  [ -f "$p" ] || fail "$CUR: no output file for $target: '$p'" "$log"
  printf -v "$var" '%s' "$p"
}
session() { "$1" < "$2" > "$3" 2> "$3.err"; rc=$?; }

begin "c_ui_probe builds the probe of the frame toy in release and in san"
build_out probe_rel "$REL" "$P:probe"
build_out probe_san "$SAN" "$P:probe"

begin "the frame session is byte-identical to session.out, twice in each mode (so across runs and modes), exit 0, nothing on stderr"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  for n in 1 2; do
    session "$bin" "$prod/session.in" "$out/s.$mode.$n"
    [ "$rc" = 0 ] || fail "$CUR: $mode run $n exited $rc" "$out/s.$mode.$n"
    [ ! -s "$out/s.$mode.$n.err" ] || fail "$CUR: $mode run $n wrote to stderr" "$out/s.$mode.$n.err"
    cmp -s "$out/s.$mode.$n" "$prod/session.out" || { diff "$prod/session.out" "$out/s.$mode.$n" > "$out/d.txt"; fail "$CUR: $mode run $n differs from session.out" "$out/d.txt"; }
  done
done
echo "  $(wc -l < "$prod/session.out") lines, 4 identical runs"

begin "the facts in the transcript, reply by reply (selftest/ui_frame_product/check.py)"
python3 -I "$prod/check.py" session "$prod/session.in" "$out/s.san.1" > "$out/facts.txt" 2>&1 || fail "$CUR" "$out/facts.txt"
echo "  coords, Bulgarian label texts (one in a font that has its glyph), ink 0 and a frame unchanged by ink, a tap that runs"
echo "  the queued press at its time, clipped 1 -> 0, life lines, the hit query firing nothing, tap and missed under the"
echo "  overlay, crop pixels, the work an animation posts run inside the frame"

begin "a frame changes no timing: the animation's work has the same trace with and without frames between the advances"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  session "$bin" "$prod/anim_frame.in" "$out/af.$mode"
  [ "$rc" = 0 ] && [ ! -s "$out/af.$mode.err" ] || fail "$CUR: anim_frame ($mode) exited $rc" "$out/af.$mode"
  session "$bin" "$prod/anim_plain.in" "$out/ap.$mode"
  [ "$rc" = 0 ] && [ ! -s "$out/ap.$mode.err" ] || fail "$CUR: anim_plain ($mode) exited $rc" "$out/ap.$mode"
  python3 -I "$prod/check.py" anim "$prod/anim_frame.in" "$out/af.$mode" "$prod/anim_plain.in" "$out/ap.$mode" \
    > "$out/anim.txt" 2>&1 || fail "$CUR ($mode)" "$out/anim.txt"
done

begin "a strict protocol for the new commands: every malformed form is an err line (transcript bad.out), exit 1, nothing on stderr; a frame over the budget is err frame too-large; every broken model interface is err model-contract"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  session "$bin" "$prod/bad.in" "$out/b.$mode"
  [ "$rc" = 1 ] || fail "$CUR: $mode exited $rc, wanted 1" "$out/b.$mode"
  [ ! -s "$out/b.$mode.err" ] || fail "$CUR: $mode wrote to stderr" "$out/b.$mode.err"
  cmp -s "$out/b.$mode" "$prod/bad.out" || { diff "$prod/bad.out" "$out/b.$mode" > "$out/d.txt"; fail "$CUR: $mode differs from bad.out" "$out/d.txt"; }
done
# the frame over the budget, each broken model interface (display, pointer, tick, settle, apply result, scratch)
python3 -I "$prod/check.py" bad "$prod/bad.in" "$out/b.san" > "$out/bad.txt" 2>&1 || fail "$CUR: the typed errors" "$out/bad.txt"

begin "crop is bounded by the payload: 160x51 is 51 lines of 1280 hex digits, 160x52 is err crop bad-arguments"
printf 'open 0 1\nframe\ncrop 0 0 160 51\ncrop 0 0 160 52\nquit\n' | "$probe_san" > "$out/crop.txt" 2>&1; rc=$?
[ "$rc" = 1 ] || fail "$CUR: the probe exited $rc, wanted 1 (one err line)" "$out/crop.txt"
python3 -I "$prod/check.py" crop "$out/crop.txt" > "$out/cropc.txt" 2>&1 || fail "$CUR" "$out/cropc.txt"

echo "ui frame selftest passed"
