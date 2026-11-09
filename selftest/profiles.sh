#!/usr/bin/env bash
# Self-test of `rigor policy-check` (T127): profile and level floors computed from the facts of a small product
# (selftest/profiles_product, copied to a scratch package). Red: a module that calls read(2) declared `pure`
# (F-adapter), a (const uint8_t *, size_t) API declared `adapter` only (F-parser), an L2 module that an L3 module
# depends on (level floor; a `data` edge to an L1 module is exempt). Green: the corrected policy, and the
# `--emit-profiles` output pasted back. Every case runs twice and must give byte-identical results.
# Needs bash, python3 (stdlib), tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
scratch="selftest/scratch_pf"
pkg="//selftest/scratch_pf"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT
RIGOR=(gate/rigor)
PY=(python3 -I -B)

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }

NAMES="rd calc hdr task flag state base top shape user"

rm -rf "$scratch"
cp -r selftest/profiles_product "$scratch"

cat > "$out/tool.py" <<'PY'
import json, os, re, shutil, sys

PKG = "//selftest/scratch_pf:"
# module -> (profile, level) of the corrected policy
GOOD = {"rd": ("adapter", "L2"), "calc": ("pure", "L2"), "hdr": ("parser", "L2"), "task": ("concurrent", "L2"),
        "flag": ("concurrent", "L2"), "state": ("wiring", "L2"), "base": ("pure", "L3"), "top": ("pure", "L3"),
        "shape": ("pure", "L1"), "user": ("pure", "L3")}

def collect(log, facts, st):
    os.makedirs(facts); os.makedirs(st)
    for line in open(log):
        m = re.match(r"^root//selftest/scratch_pf:(\w+)_(s|facts)\s+(\S+)$", line.strip())
        if m:
            shutil.copy(m.group(3), os.path.join(st if m.group(2) == "s" else facts, m.group(1) + ".json"))

def policy(dest, *changes):
    """policy DEST [name=profile|-,level ...]: the corrected policy with changes; profile `-` drops the key"""
    mods = dict(GOOD)
    for c in changes:
        name, value = c.split("=")
        prof, level = value.split(",")
        mods[name] = (prof, level)
    text = ""
    for name in sorted(mods):
        prof, level = mods[name]
        text += '[module."%s%s"]\nlevel = "%s"\n' % (PKG, name, level)
        if prof != "-":
            text += 'profile = ["%s"]\n' % prof
    open(dest, "w").write(text)

def paste(emitted, base_policy, dest):
    """paste EMITTED BASE DEST: BASE with each module's emitted `profile = [...]` line inserted in its table"""
    prof, label = {}, None
    for line in open(emitted):
        line = line.rstrip("\n")
        if line.startswith("[module."):
            label = line
        elif line.startswith("profile = "):
            prof[label] = line
    outp, cur = [], None
    for line in open(base_policy).read().splitlines():
        if line.startswith("[module."):
            cur = line
            outp.append(line)
            outp.append(prof[cur])
        elif not line.startswith("profile = "):
            outp.append(line)
    open(dest, "w").write("\n".join(outp) + "\n")

def check(result, *expected):
    doc = json.load(open(result))
    def render(f):
        extra = f.get("symbol") or f.get("function") or f.get("dependent") or f.get("profile") or ""
        return "%s:%s:%s:%s" % (f["rule"], f["module"].split(":")[-1], f.get("floor_rule", ""), extra)
    got = sorted(render(f) for f in doc["findings"] if f["severity"] == "error")
    if got != sorted(expected):
        print("  wanted %s\n  got    %s" % (sorted(expected), got)); sys.exit(1)
    if (doc["status"] == "PASS") != (not expected):
        print("  status %s does not match" % doc["status"]); sys.exit(1)

def floor(result, name, want):
    doc = json.load(open(result))
    got = [f["floor"] for f in doc["findings"] if f["rule"] == "profile-floor" and f["module"] == PKG + name]
    if got != [want.split(",")]:
        print("  floor of %s: wanted %s got %s" % (name, want, got)); sys.exit(1)

def same(a, b):
    if open(a, "rb").read() != open(b, "rb").read():
        print("  %s and %s differ" % (a, b)); sys.exit(1)

COMMANDS = {"collect": collect, "policy": policy, "paste": paste, "check": check, "floor": floor, "same": same}
COMMANDS[sys.argv[1]](*sys.argv[2:])
PY
tool() { "${PY[@]}" "$out/tool.py" "$@"; }

# case <name> <want-exit> <policy> [extra policy-check args] -- <expected error>... ; twice, byte-identical
case_run() {
  local name="$1" want="$2" pol="$3"; shift 3
  local extra=() expected=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do extra+=("$1"); shift; done
  [ "${1:-}" = "--" ] && shift
  expected=("$@")
  local i rc
  for i in 1 2; do
    "${RIGOR[@]}" policy-check --policy "$pol" --facts "$out/facts" --structure "${ST:-$out/st}" --architecture "$out/architecture.toml" \
      "${extra[@]}" --out "$out/$name.$i.json" > "$out/$name.$i.txt" 2> "$out/$name.$i.err"
    rc=$?
    [ "$rc" = "$want" ] || fail "$CUR: $name run $i exited $rc, wanted $want" "$out/$name.$i.txt"
  done
  tool check "$out/$name.1.json" "${expected[@]}" || fail "$CUR: $name findings differ" "$out/$name.1.txt"
  tool same "$out/$name.1.json" "$out/$name.2.json" || fail "$CUR: $name is not deterministic"
  cmp -s "$out/$name.1.txt" "$out/$name.2.txt" || fail "$CUR: $name console output is not deterministic"
  echo "  $name -> exit $want ${expected[*]:-}"
}

begin "build the symbol and structure facts of 10 modules on RE"
args=(); for n in $NAMES; do args+=("$pkg:${n}_facts" "$pkg:${n}_s"); done
run "$out/build.log" build "${args[@]}" --show-full-output || fail "$CUR: buck2 build failed" "$out/build.log"
tool collect "$out/build.log" "$out/facts" "$out/st" || fail "$CUR: collect"
ls "$out/facts" | wc -l | xargs echo "  fact files:"

cat > "$out/architecture.toml" <<EOT
[layers]
order = ["low", "high"]
[layer."low"]
modules = ["$pkg:rd", "$pkg:calc", "$pkg:hdr", "$pkg:task", "$pkg:flag", "$pkg:state", "$pkg:base", "$pkg:shape"]
[layer."high"]
modules = ["$pkg:top", "$pkg:user"]
[[edge]]
from = "$pkg:top"
to = "$pkg:base"
kind = "pure"
[[edge]]
from = "$pkg:user"
to = "$pkg:shape"
kind = "data"
EOT

begin "green: the corrected policy passes; the floors are what the facts force"
tool policy "$out/good.toml"
case_run good 0 "$out/good.toml" --require-profiles --
for want in rd=adapter hdr=parser task=concurrent flag=concurrent state=wiring calc=pure base=pure; do
  tool floor "$out/good.1.json" "${want%%=*}" "${want##*=}" || fail "$CUR: floor of ${want%%=*}"
done
echo "  floors: rd adapter, hdr parser, task and flag concurrent, state wiring, calc and base pure"

begin "red (F-adapter): a module that calls read(2) declared pure"
tool policy "$out/rd_pure.toml" "rd=pure,L2"
case_run rd_pure 1 "$out/rd_pure.toml" -- "profile-below-floor:rd:F-adapter:read"

begin "red (F-parser): a (const uint8_t *, size_t) API declared adapter only"
tool policy "$out/hdr_adapter.toml" "hdr=adapter,L2"
case_run hdr_adapter 1 "$out/hdr_adapter.toml" -- "profile-below-floor:hdr:F-parser:hdr_parse"

begin "red (F-concurrent, F-wiring): pthread calls, an atomic builtin and static state declared pure"
tool policy "$out/others.toml" "task=pure,L2" "flag=pure,L2" "state=pure,L2"
case_run others 1 "$out/others.toml" -- "profile-below-floor:task:F-concurrent:pthread_create" \
  "profile-below-floor:task:F-concurrent:pthread_join" "profile-below-floor:flag:F-concurrent:__atomic_load_n" \
  "profile-below-floor:state:F-wiring:g_count"

begin "red (level floor): an L2 module that an L3 module depends on; the data edge to an L1 module is exempt"
tool policy "$out/base_l2.toml" "base=pure,L2"
case_run base_l2 1 "$out/base_l2.toml" -- "level-below-floor:base::$pkg:top"

begin "red (fail closed): a module with units but no structure facts; a policy module with a level but no facts"
mkdir -p "$out/st_short"
for f in "$out"/st/*.json; do [ "$(basename "$f")" = calc.json ] || cp "$f" "$out/st_short/"; done
ST="$out/st_short" case_run no_structure 1 "$out/good.toml" -- "structure-missing:calc::"
tool policy "$out/ghost.toml" "ghost=pure,L2"
case_run no_facts 1 "$out/ghost.toml" -- "facts-missing:ghost::"
if "${RIGOR[@]}" policy-check --policy "$out/good.toml" --facts "$out/facts" > "$out/nost.txt" 2>&1; then
  fail "$CUR: policy-check without --structure passed"
fi
echo "  policy-check without --structure is refused"

begin "red (profile-missing, profile-unknown): info without --require-profiles, an error with it; an unknown name is an error"
tool policy "$out/missing.toml" "calc=-,L2"
case_run missing 0 "$out/missing.toml" --
case_run missing_req 1 "$out/missing.toml" --require-profiles -- "profile-missing:calc::"
tool policy "$out/unknown.toml" "calc=bogus,L2"
case_run unknown 1 "$out/unknown.toml" -- "profile-unknown:calc::bogus"

begin "--emit-profiles: the output of a policy with no profiles, pasted back, passes with --require-profiles"
tool policy "$out/bare.toml" "rd=-,L2" "calc=-,L2" "hdr=-,L2" "task=-,L2" "flag=-,L2" "state=-,L2" "base=-,L3" "top=-,L3" "shape=-,L1" "user=-,L3"
for i in 1 2; do
  "${RIGOR[@]}" policy-check --policy "$out/bare.toml" --facts "$out/facts" --structure "$out/st" --architecture "$out/architecture.toml" \
    --emit-profiles > "$out/emit.$i.txt" 2> "$out/emit.$i.err" || fail "$CUR: emit exited $?" "$out/emit.$i.err"
done
cmp -s "$out/emit.1.txt" "$out/emit.2.txt" || fail "$CUR: emit output is not deterministic"
grep -q 'profile = \["adapter"\]' "$out/emit.1.txt" || fail "$CUR: no adapter line" "$out/emit.1.txt"
sed 's/^/    /' "$out/emit.1.txt"
tool paste "$out/emit.1.txt" "$out/bare.toml" "$out/pasted.toml" || fail "$CUR: paste"
case_run pasted 0 "$out/pasted.toml" --require-profiles --

echo "selftest/profiles.sh: all checks passed in $SECONDS s"
