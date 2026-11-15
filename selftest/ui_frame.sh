#!/usr/bin/env bash
# Self-test of the probe's frame facts (U05a, docs/ui-model.md "Frame facts"), called by selftest/ui.sh: the frame toy in
# selftest/ui_frame_product is built as a probe in release and san; its scripted sessions (session.in, bad.in) must give
# the checked-in transcripts byte for byte, twice per mode; and the facts the transcript holds are checked one by one
# (node coords, label texts with Bulgarian, `clipped` with and without room, the hit query firing nothing, the tap and
# `ok apply missed` under the overlay, `ok apply` and the tap reaching the button without it, ink 0 of a hidden label,
# lifecycle lines, a frame over the budget as `err frame too-large`, crop pixels and its payload bound).
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

begin "the facts in the transcript, reply by reply"
python3 -I - "$prod/session.in" "$out/s.san.1" > "$out/facts.txt" 2>&1 <<'PY' || fail "$CUR" "$out/facts.txt"
import sys
cmds = open(sys.argv[1]).read().splitlines()
lines = open(sys.argv[2], encoding="ascii").read().split("\n")
assert lines.pop() == "" and lines.pop(0) == "ui-probe/1 ready frame-facts ink hit-test tap apply-missed crop"
replies, at = [], 0
for cmd in cmds:        # every reply is one line, or `ok <name> lines <n>` and n lines
    head = lines[at]; words = head.split(" "); at += 1
    n = int(words[3]) if len(words) == 4 and words[0] == "ok" and words[2] == "lines" else 0
    replies.append((cmd, head, lines[at:at + n])); at += n
assert at == len(lines), "lines after the last reply"
def reply(i, cmd):
    assert replies[i][0] == cmd, (i, replies[i][0], cmd)
    return replies[i][1], replies[i][2]
def frame(i):
    """The lines of a frame reply: the head, then each node of the walk in index order, then the life lines."""
    head, body = reply(i, "frame")
    assert head.startswith("ok frame lines "), head
    count = int(body[0].split("\t")[2])
    nodes = [l.split("\t")[1] for l in body if l.startswith("node\t")]
    assert body[0].startswith("lvprobe\t1\t") and body[1].startswith("frame\t") and nodes == [str(k) for k in range(count)]
    kinds = [l.split("\t")[0] for l in body]
    assert kinds == sorted(kinds, key=lambda k: k == "life") and set(kinds) <= {"lvprobe", "frame", "node", "label", "fit", "region", "life"}
    return body
def need(body, line, what):
    assert line in body, "%s: %r missing" % (what, line)
def fit(body, node):
    return [l for l in body if l.startswith("fit\t%d\t" % node)][0].split("\t")
first = frame(1)
assert first[0] == "lvprobe\t1\t13" and first[1].startswith("frame\t160\t120\t") and len(first[1].split("\t")[3]) == 8
need(first, "node\t3\t1\t1\tlv_button\t8\t30\t97\t59\t0\t1\t-1\t-1\t0\t0\t2196f3\t255\t255\t1\t0\t0", "button coords")
need(first, "label\t4\t-\t16\t0\t1\t0\t0\t1\t39\t16\t39\t16\t=Press\t-", "button label")
need(first, "fit\t4\t1\t0\t35,40,72,49\t30,33,76,52\t0\t0", "button label fit")
need(first, "node\t10\t1\t1\tlv_obj\t0\t0\t159\t119\t0\t0\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0", "overlay, not clickable")
assert reply(4, "hit-test 53 45")[0] == "ok hit-test 3" and reply(5, "trace")[0] == "ok trace lines 0"
assert reply(6, "crop 140 100 8 2")[1] == ["ff0000ff" * 4 + "0000ffff" * 4] * 2, "crop pixels"
ink = reply(7, "ink")[1]
need(ink, "ink\t7\t0\t-\t000000\t000000\t000000\t000000", "ink 0 of the hidden label")
need(ink, "ink\t8\t8\t140,100,143,101\tff0000\tff0000\tffffff\tffffff", "ink of the red swatch")
assert reply(8, "apply 3 1 0 -")[0] == "ok apply"
assert reply(9, "trace")[1] == ["1\tbutton_pressed\t1000", "2\tpointer_clicked\t1000", "3\tbutton_clicked\t1000",
                               "4\tpress\t1000"]
shown = frame(10)
need(shown, "label\t5\t-\t16\t0\t1\t0\t0\t1\t60\t16\t60\t16\t=\\xd0\\x93\\xd0\\xbe\\xd1\\x82\\xd0\\xbe\\xd0\\xb2\\xd0\\xbe\t-", "notice in Bulgarian")
assert fit(shown, 5)[2] == "1" and fit(shown, 5)[6] == "6", "the notice is drawn, its 6 Cyrillic glyphs are placeholders"
assert fit(shown, 6)[-1] == "0" and fit(frame(12), 6)[-1] == "1" and fit(frame(14), 6)[-1] == "0", "clipped squeezed, not with room"
assert [l for l in frame(16) if l.startswith("life")] == ["life\t1\tcreated\t0\t-1\t1\tlv_label"]
assert [l for l in frame(18) if l.startswith("life")] == ["life\t2\tdeleted\t0\t11\t1\tlv_label"]
covered = frame(20)
need(covered, "node\t10\t1\t1\tlv_obj\t0\t0\t159\t119\t0\t1\t-1\t-1\t0\t0\tffffff\t0\t0\t1\t0\t0", "overlay, clickable")
assert reply(21, "trace")[0] == "ok trace lines 0"
assert reply(22, "hit-test 53 45")[0] == "ok hit-test 10", "the hit query names the overlay"
assert reply(23, "trace")[0] == "ok trace lines 0", "the hit query fired a handler"
assert reply(24, "tap 53 45")[0] == "ok tap 10 10", "the tap goes to the overlay"
# pointer_clicked: the probe's tap went through the product's own pointer indev
assert reply(25, "trace")[1] == ["5\toverlay_pressed\t1000", "6\tpointer_clicked\t1000", "7\toverlay_clicked\t1000"]
assert reply(26, "apply 3 1 0 -")[0] == "ok apply missed"
assert reply(27, "trace")[1] == ["8\toverlay_pressed\t1000", "9\tpointer_clicked\t1000", "10\toverlay_clicked\t1000"], "missed"
assert reply(28, "apply 3 3 0 -")[0] == "ok apply"
frame(29)
assert reply(30, "hit-test 53 45")[0] == "ok hit-test 3" and reply(31, "tap 53 45")[0] == "ok tap 3 3"
assert reply(32, "trace")[1] == ["11\tbutton_pressed\t1000", "12\tpointer_clicked\t1000", "13\tbutton_clicked\t1000"]
assert reply(33, "apply 3 1 0 -")[0] == "ok apply"
assert all(len(r[1]) + sum(len(l) + 1 for l in r[2]) < 65536 for r in replies)
print("ok")
PY
echo "  coords, Bulgarian label text, clipped 1 -> 0, hit query names the overlay and fires nothing, tap and missed under it, ink 0, life lines, crop"

begin "a strict protocol for the new commands: every malformed form is an err line (transcript bad.out), exit 1, nothing on stderr; a frame over the budget is err frame too-large"
for mode in rel san; do
  eval "bin=\$probe_$mode"
  session "$bin" "$prod/bad.in" "$out/b.$mode"
  [ "$rc" = 1 ] || fail "$CUR: $mode exited $rc, wanted 1" "$out/b.$mode"
  [ ! -s "$out/b.$mode.err" ] || fail "$CUR: $mode wrote to stderr" "$out/b.$mode.err"
  cmp -s "$out/b.$mode" "$prod/bad.out" || { diff "$prod/bad.out" "$out/b.$mode" > "$out/d.txt"; fail "$CUR: $mode differs from bad.out" "$out/d.txt"; }
done
# the frame of APP_MANY labels does not fit one reply: a typed error that poisons, never a truncated reply
[ "$(tail -n 3 "$out/b.san")" = "$(printf 'err frame too-large\nerr semantic not-open\nok quit')" ] || fail "$CUR: the frame over the budget" "$out/b.san"

begin "crop is bounded by the payload: 160x51 is 51 lines of 1280 hex digits, 160x52 is err crop bad-arguments"
printf 'open 0 1\nframe\ncrop 0 0 160 51\ncrop 0 0 160 52\nquit\n' | "$probe_san" > "$out/crop.txt" 2>&1
python3 -I - "$out/crop.txt" <<'PY' || fail "$CUR" "$out/crop.txt"
import sys
lines = open(sys.argv[1]).read().split("\n")
at = lines.index("ok crop lines 51")
rows = lines[at + 1:at + 52]
assert all(len(r) == 1280 and r == r.lower() and set(r) <= set("0123456789abcdef") for r in rows)
assert rows[0][:8] == "ffffffff" and lines[at + 52] == "err crop bad-arguments" and lines[at + 53] == "ok quit"
PY

echo "ui frame selftest passed"
