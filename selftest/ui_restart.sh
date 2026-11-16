#!/usr/bin/env bash
# Self-test of the explorer's declared countdown restart (U05d, docs/ui-explore.md "Countdown restart"), called by
# selftest/ui.sh: the unit tests' stub probe in its mode pcount (every tap restarts a countdown 298 s -> 300 s, drawn as
# LVGL draws it: crc, the screen's and the label's regions follow the text) with a catalogue that declares the
# countdown's role gives one info ambient-restart and no noop-tap-effect, and a countdown that skips forward (pskip)
# stays noop-tap-effect; and the rule's frame clause accepts a real LVGL repaint of one label (the frame toy's probe,
# selftest/ui_frame_product, run live on its scripted session: `Frame` -> `Done`, with the regions of every node that
# covers the label) and rejects the same frame with a region of a node that does not cover it changed.
# Needs bash, python3 (stdlib) and tools/buck2. Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(python3 -I -B gate/rigor)
REL=toolchains//:linux_release
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

step=0
fail() { echo "FAIL [restart $step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[restart $step] $1"; CUR="$1"; }

# countdown <name> <stub mode> <wanted exit> <python check of the findings F>: replays a complement tap and a root tap of
# the open state against the stub in that mode, with the catalogue that declares the countdown role
countdown() {
  local name="$1" mode="$2" want="$3" check="$4"
  printf '#!/bin/sh\nexec python3 -I -B %s %s\n' "$root/gate/tests/data/ui_explore/stub_probe.py" "$mode" > "$out/stub-$mode"
  chmod +x "$out/stub-$mode"
  python3 -I -B -c 'import sys; sys.path[:0] = [sys.argv[1]]; from tests.test_ui_explore_restart import catalogue_text; open(sys.argv[2], "w").write(catalogue_text())' "$root/gate" "$out/countdown.toml" || fail "$CUR: the countdown catalogue"
  printf '{"schema": "ui-explore-paths/1", "criteria": [], "paths": [["open 1000 7", "probe-blank"], ["open 1000 7", "probe-screen"]]}' > "$out/countdown.paths"
  "${RIGOR[@]}" ui-explore --probe "$out/stub-$mode" --catalogue "$out/countdown.toml" --strategy replay --paths "$out/countdown.paths" --out "$out/x.$name.json" > "$out/x.$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/x.$name.txt"
  python3 -I - "$out/x.$name.json" "$check" <<'PY' || fail "$CUR: $name: wanted $check" "$out/x.$name.json"
import json, sys
F = [json.loads(line) for line in open(sys.argv[1])]
sys.exit(0 if eval(sys.argv[2]) else 1)
PY
}

begin "a declared countdown restart (the stub's pcount: every tap restarts 298 s to 300 s, crc and covering regions repainted) is no tap effect: the complement and the root tap refused, one info ambient-restart (state, node), no noop-tap-effect; a countdown that skips forward (pskip, 298 s to 290 s) stays noop-tap-effect on both"
countdown restart pcount 0 '[(f["check"], f["severity"], f["path"], f["observed"]) for f in F] == [("ambient-restart", "info", ["open 1000 7", "probe-blank"], {"word": "probe-blank", "node": "count", "old": 298, "new": 300})]'
countdown skip pskip 1 'sorted((f["check"], f["observed"]["word"], f["observed"]["changed"]) for f in F) == [("noop-tap-effect", w, ["patches", "semantic", "frame"]) for w in ("probe-blank", "probe-screen")]'
echo "  pcount: one ambient-restart (info), exit 0; pskip: two noop-tap-effect, exit 1"

begin "the rule's frame clause on a real LVGL frame: the frame toy's probe, run live on its session, repaints its title (Frame -> Done) with the regions of the nodes that cover it: accepted; with a far node's region changed: rejected"
log="$out/frame_build.log"
"${B[@]}" build --target-platforms "$REL" //selftest/ui_frame_product:probe --show-output > "$log" 2>&1 || fail "$CUR: build of the frame toy's probe" "$log"
probe="$(awk '/buck-out/ {print $2}' "$log" | tail -1)"
[ -f "$probe" ] || fail "$CUR: no probe binary" "$log"
"$probe" < selftest/ui_frame_product/session.in > "$out/frame.out" 2> "$out/frame.err" || fail "$CUR: the frame toy's session failed" "$out/frame.err"
python3 -I -B - "$root/gate" "$out/frame.out" <<'PY' > "$out/frame.txt" 2>&1 || fail "$CUR: the real frame" "$out/frame.txt"
import sys
sys.path[:0] = [sys.argv[1]]
from rigor_lib import ui_explore_restart as r
from tests.test_ui_explore_restart_rule import real_repaint
before, after = real_repaint(open(sys.argv[2]).read(), "Frame", "Done")
regions = sorted(a.split("\t")[1] for a, b in zip(before, after) if a != b and a.startswith("region\t"))
assert len(regions) > 3, regions
labels = {"title": ("Frame", "Done")}
assert r.frame_reason(before, after, [], labels) is None, r.frame_reason(before, after, [], labels)
far = [i for i, line in enumerate(after) if line.startswith("region\t8\t")][0]
bad = list(after)
bad[far] = "region\t8\t00000000"
assert r.frame_reason(before, bad, [], labels) == "frame record region 8", r.frame_reason(before, bad, [], labels)
print("  repainted regions", " ".join(regions), "accepted; region 8 changed: rejected")
PY
cat "$out/frame.txt"
