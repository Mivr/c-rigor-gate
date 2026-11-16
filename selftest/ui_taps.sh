#!/usr/bin/env bash
# Self-test of the explorer's U05e changes (docs/ui-explore.md "Cost", "Scene taps", "Taps under a layer", the pad's
# digit map, boot seeds and prefixes), called by selftest/ui.sh, through `rigor ui-explore` on the unit tests' scene
# stub (gate/tests/data/ui_explore/stub_scene.py, one mode per case) and its catalogue: a bfs derives every state's taps
# from its scene; under --contract a tap on a target inert under a modal dialog is refused, an effect there is
# blocked-target-live, a tap outside a dismissing snackbar is `dismissed` (a wrong one tap-misrouted), a tap that only
# removes a pass-through banner is tap-swallowed-first, and without --contract the dialog's taps are judged as before;
# the digit map types a code; boot seeds and a prefix; the budget cuts a bfs into depth-unsaturated reason budget.
# Needs bash and python3 (stdlib). Scratch lives under $TMPDIR.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
RIGOR=(python3 -I -B gate/rigor)
CAT=gate/tests/data/ui_explore/scene.events.toml
CONTRACT=selftest/ui_canary_product/canary.toml
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

step=0
fail() { echo "FAIL [taps $step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[taps $step] $1"; CUR="$1"; }

# explore <name> <stub mode> <wanted exit> <python check of the findings F and the summary S> <ui-explore args...>
explore() {
  local name="$1" mode="$2" want="$3" check="$4"
  shift 4
  printf '#!/bin/sh\nexec python3 -I -B %s %s\n' "$root/gate/tests/data/ui_explore/stub_scene.py" "$mode" > "$out/stub-$mode"
  chmod +x "$out/stub-$mode"
  "${RIGOR[@]}" ui-explore --probe "$out/stub-$mode" --catalogue "$CAT" --out "$out/$name.f" --summary "$out/$name.s" \
    "$@" > "$out/$name.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: ui-explore $name exited $rc, wanted $want" "$out/$name.txt"
  python3 -I - "$out/$name.f" "$out/$name.s" "$check" <<'PY' || fail "$CUR: $name: wanted $check" "$out/$name.f"
import json, sys
F = [json.loads(line) for line in open(sys.argv[1])]
S = json.load(open(sys.argv[2]))
C = sorted((f["check"], f["path"][-1]) for f in F)
sys.exit(0 if eval(sys.argv[3]) else 1)
PY
}

paths() {
  printf '{"schema": "ui-explore-paths/1", "criteria": [], "paths": [["open 1000 7", "tap@go#0"], ["open 1000 7", "tap-go"], ["open 1000 7", "blank-right"], ["open 1000 7", "go"]]}' > "$out/layers.paths"
}
paths
REPLAY=(--strategy replay --paths "$out/layers.paths" --budget-s 120)

begin "scene-scoped taps: a bfs taps the centre and the 3x3 grid of every enabled interactive node of each state (tap@go#0..8), and the disabled control and the blank area (blank#i), never a disabled one as u2"
explore bfs plain 1 '"tap@go#8" in S["outcomes"] and "blank#0" in S["outcomes"] and "tap@off#0" not in S["outcomes"] and S["findings"]["taps-capped"] == 0' \
  --strategy bfs --origin-ms 1000 --seed 7 --depth 1 --max-states 50 --budget-s 120
echo "  $(python3 -I -c 'import json,sys; print(len([w for w in json.load(open(sys.argv[1]))["outcomes"] if "@" in w or "#" in w]), "scene words tapped")' "$out/bfs.s")"

begin "the layer policy under --contract: inert under the modal dialog = refused (no intent-missed, no tap-misrouted); an effect there = blocked-target-live; a tap outside the snackbar = dismissed; a wrong dismiss = tap-misrouted; a tap that only removes the pass-through banner = tap-swallowed-first"
explore dialog dialog 0 'F == [] and S["outcomes"]["tap-go"]["layer inert dscrim"] == 1' "${REPLAY[@]}" --contract "$CONTRACT"
explore live dialoglive 1 'C == [("blocked-target-live", "go"), ("blocked-target-live", "tap-go"), ("blocked-target-live", "tap@go#0")]' "${REPLAY[@]}" --contract "$CONTRACT"
explore snack snack 0 'F == [] and S["outcomes"]["blank-right"]["tap dismissed"] == 1' "${REPLAY[@]}" --contract "$CONTRACT"
explore bad snackbad 1 'C == [("tap-misrouted", "blank-right"), ("tap-misrouted", "tap-go"), ("tap-misrouted", "tap@go#0")]' "${REPLAY[@]}" --contract "$CONTRACT"
explore banner banner 1 'C == [("noop-tap-effect", "blank-right"), ("tap-swallowed-first", "tap-go"), ("tap-swallowed-first", "tap@go#0")]' "${REPLAY[@]}" --contract "$CONTRACT"
echo "  dialog: no finding; dialoglive: 3 blocked-target-live (two taps, one u1); snack: dismissed; snackbad: 3 tap-misrouted; banner: 2 tap-swallowed-first"

begin "without --contract the same dialog taps are judged as before: intent-missed and tap-misrouted"
explore nocontract dialog 1 'C == [("intent-missed", "go"), ("intent-missed", "tap-go"), ("intent-missed", "tap@go#0"), ("tap-misrouted", "tap-go"), ("tap-misrouted", "tap@go#0")]' "${REPLAY[@]}"

begin "the pad's digit map types each digit as its own intent; boot seeds run the bfs once per seed; a prefix starts it after its words"
printf '{"schema": "ui-explore-paths/1", "criteria": [], "paths": [["open 1000 7", "pad-map-12"], ["open 1000 7", "pad-12"]]}' > "$out/pad.paths"
explore pad keyed 0 'S["outcomes"]["pad-map-12"] == {"apply ok": 3} and S["outcomes"]["pad-12"] == {"apply ok": 2, "apply refused": 1}' \
  --strategy replay --paths "$out/pad.paths" --budget-s 120
explore seeds seeded 1 '[d["seed"] for d in S["detail"]["boot_seeds"]] == [7, 8] and {f["path"][0] for f in F if f["path"]} == {"open 1000 7", "open 1000 8"}' \
  --strategy bfs --origin-ms 1000 --boot-seeds catalogue --depth 1 --max-states 3 --budget-s 120
explore prefix snack 1 'all(f["path"][:2] == ["open 1000 7", "show"] for f in F if len(f["path"]) > 1)' \
  --strategy bfs --origin-ms 1000 --seed 7 --prefix shown --depth 1 --max-states 3 --budget-s 120

begin "the cost model: one path that cannot fit the budget is refused up front (exit 2); a bfs the measured wall-clock budget cuts ends with depth-unsaturated reason budget, exit 1, nothing evaluated"
printf '{"schema": "ui-explore-paths/1", "criteria": [], "paths": [["open 1000 7", "at 9000", "at 10000"]]}' > "$out/far.paths"
"${RIGOR[@]}" ui-explore --probe "$out/stub-plain" --catalogue "$CAT" --out "$out/refused.f" --strategy replay \
  --paths "$out/far.paths" --budget-s 1 > "$out/refused.txt" 2>&1
rc=$?
[ "$rc" = 2 ] && grep -q "one path of this run could take" "$out/refused.txt" || fail "$CUR: wanted exit 2 and the refusal, got $rc" "$out/refused.txt"
explore cut slow 1 '[f["observed"]["reasons"] for f in F if f["check"] == "depth-unsaturated"] == [["budget"]] and S["budget_spent"] and S["evaluated"] == []' \
  --strategy bfs --origin-ms 1000 --seed 7 --depth 3 --max-states 50 --budget-s 8
echo "  refused: $(grep -o 'one path of this run could take [0-9]* ms' "$out/refused.txt"); the budget cut: depth-unsaturated [budget]"
