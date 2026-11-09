#!/usr/bin/env bash
# Self-test of `gate//rt:require` and CHECK_TRAPS (T128), in `release` and `san`.
# A throwaway product (selftest/require_product, copied to a scratch package) has a module with a guard,
# `rigor_require(index < CAP)`, before an array read. Checked:
#  * tests: in range passes; out of range inside CHECK_TRAPS passes (one check each); out of range outside it fails as
#    a death by signal (release) or an exit after the sanitizer's SIGILL report (san); CHECK_TRAPS fails, with the
#    reason named, on an expression that returns, exits, hangs, dies by SIGSEGV, SIGABRT or makes an ASan report;
#  * gates: `rigor buckfiles`, `rigor facts` (semantic-suppressions and symbols) and `rigor structure` accept the
#    dependency with no allow_builtins and no policy entry; another `gate//` dependency fails as before, and so does a
#    product that calls __builtin_trap itself;
#  * T131: the trap in a product's own header is not the gate's (`forbidden-builtin`) although the target depends on the
#    gate's library; `rigor_require` is reserved (`#define`, `#undef`, a function of that name, its address:
#    `reserved-identifier`); `rigor guards` counts the call sites and judges the declared budget (within the density
#    cap passes; over the sites and over the cap fail);
#  * mutation: the guard's mutants exist and the CHECK_TRAPS tests kill them (the boundary one included); the same
#    module tested without CHECK_TRAPS leaves them as survivors;
#  * everything twice, the second time from sources stamped with a nonce so that nothing comes from the cache, and the
#    results must be identical.
# Needs bash, python3 (stdlib), tools/buck2 and the RE farm.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
RIGOR=(gate/rigor)
PY=(python3 -I -B)
scratch="selftest/scratch_rq"
pkg="//selftest/scratch_rq"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }

rm -rf "$scratch"
cp -r selftest/require_product "$scratch"

cat > "$out/tool.py" <<'PY'
import json, os, re, shutil, sys

PKG = "//selftest/scratch_rq:"

def collect(log, dest, suffix):
    """collect LOG DEST SUFFIX: every `root//<pkg>:<name>_<SUFFIX> <path>` line of a --show-output log to DEST/<name>.json"""
    os.makedirs(dest, exist_ok=True)
    pattern = re.compile(r"^root//\S*?:(\w+?)_" + suffix + r"\s+(\S+)$")
    for line in open(log):
        m = pattern.match(line.strip())
        if m:
            shutil.copy(m.group(2), os.path.join(dest, m.group(1) + ".json"))

def collect_modes(log, dest, suffix):
    """collect_modes LOG DEST SUFFIX: the targets that have both `<name>_facts<SUFFIX>` and `[calls]` to DEST/<name>.json, .calls.json"""
    os.makedirs(dest, exist_ok=True)
    pattern = re.compile(r"^root//\S*?:(\w+?)_facts" + suffix + r"(\[calls\])?\s+(\S+)$")
    facts, calls = {}, {}
    for line in open(log):
        m = pattern.match(line.strip())
        if m:
            (calls if m.group(2) else facts)[m.group(1)] = m.group(3)
    for name in calls:
        shutil.copy(facts[name], os.path.join(dest, name + ".json"))
        shutil.copy(calls[name], os.path.join(dest, name + ".calls.json"))

def mkfd(src, dest, *names):
    os.makedirs(dest, exist_ok=True)
    for name in names:
        shutil.copy(os.path.join(src, name + ".json"), os.path.join(dest, name + ".json"))

def policy(dest, *names):
    head = open("policy/hello.toml").read().split("[module.")[0]
    open(dest, "w").write(head + "".join('[module."%s%s"]\nallow = []\n\n' % (PKG, n) for n in names))

def levels(dest, *names):
    open(dest, "w").write("".join('[module."%s%s"]\nlevel = "L3"\n' % (PKG, n) for n in names))

def check(result, *expected):
    doc = json.load(open(result))
    got = sorted(f["rule"] + ":" + (f.get("name") or f.get("dep") or "") for f in doc["findings"] if f["severity"] == "error")
    if got != sorted(expected):
        print("  wanted %s\n  got    %s" % (sorted(expected), got)); sys.exit(1)
    if (doc["status"] == "PASS") != (not expected):
        print("  status %s does not match the findings" % doc["status"]); sys.exit(1)

def load_results(path):
    rows = [json.loads(line) for line in open(path) if line.strip()]
    return {r["id"]: r for r in rows if "id" in r}, [r for r in rows if "summary" in r]

def good(path):
    rows, summary = load_results(path)
    want = {"table/in_range": 4, "table/traps_at_cap": 1, "table/traps_far_out": 2}
    if sorted(rows) != sorted(want) or summary != [{"summary": {"total": 3, "passed": 3}}]:
        print("  unexpected rows %s %s" % (sorted(rows), summary)); sys.exit(1)
    for name, asserts in want.items():
        r = rows[name]
        if r["status"] != "pass" or r["asserts"] != asserts or r["reason"] != "":
            print("  %s: wanted a pass with %d checks, got %s" % (name, asserts, r)); sys.exit(1)

# the text each failing test must show, per mode
BAD = {
    "trap_outside": {"release": ["killed by signal 4"], "san": ["exited with status 1 before reporting", "AddressSanitizer: ILL"]},
    "traps_on_return": {"*": ["CHECK_TRAPS(table_get(0)): the expression returned, it did not trap"]},
    "traps_on_segv": {"release": ["the expression died by signal 11 (Segmentation fault), not by the trap"],
                      "san": ["the expression made a sanitizer report instead"]},
    "traps_on_overflow": {"release": ["the expression returned, it did not trap"],
                          "san": ["the expression made a sanitizer report instead: AddressSanitizer: global-buffer-overflow"]},
    "traps_on_abort": {"release": ["the expression died by signal 6 (Aborted), not by the trap"],
                       "san": ["the expression made a sanitizer report instead"]},
    "traps_on_exit": {"*": ["the expression exited with status 3, it did not trap"]},
    "traps_on_hang": {"*": ["timeout after 3000 ms, the expression did not trap"]},
    "traps_then_check": {"*": ["1 of 2 checks failed; first: ", "CHECK(1 == 2)"]},
}

def bad(path, mode):
    rows, summary = load_results(path)
    if sorted(rows) != sorted("bad/" + n for n in BAD) or summary != [{"summary": {"total": len(BAD), "passed": 0}}]:
        print("  unexpected rows %s %s" % (sorted(rows), summary)); sys.exit(1)
    for name, per_mode in BAD.items():
        r = rows["bad/" + name]
        if r["status"] != "fail":
            print("  %s: wanted a failure, got %s" % (name, r)); sys.exit(1)
        for text in per_mode.get(mode, per_mode.get("*")):
            if text not in r["reason"]:
                print("  %s: %r not in the reason %r" % (name, text, r["reason"])); sys.exit(1)
    # a CHECK_TRAPS is one check; the trap outside it kills the test before any check is reported
    if rows["bad/traps_then_check"]["asserts"] != 2 or rows["bad/traps_on_return"]["asserts"] != 1 \
            or rows["bad/trap_outside"]["asserts"] != 0:
        print("  wrong check counts: %s" % {k: v["asserts"] for k, v in rows.items()}); sys.exit(1)

def gpolicy(dest, a, b):
    open(dest, "w").write("".join('[module."%s%s"]\nguards = %s\n\n' % (PKG, n, v) for n, v in (("guards_a", a), ("guards_b", b))))

def gcheck(result, *expected):
    """the errors of `rigor guards` are exactly EXPECTED (`rule:module`), and the info rows carry the counts"""
    doc = json.load(open(result))
    got = sorted(f["rule"] + ":" + f["module"].split(":")[-1] for f in doc["findings"] if f["severity"] == "error")
    if got != sorted(expected):
        print("  wanted %s\n  got    %s" % (sorted(expected), got)); sys.exit(1)
    info = {f["module"].split(":")[-1]: (f["sites"], f["cap"]) for f in doc["findings"] if f["rule"] == "guards"}
    if info != {"guards_a": (6, 3), "guards_b": (2, 3)}:
        print("  unexpected info rows %s" % info); sys.exit(1)
    if (doc["status"] == "PASS") != (not expected):
        print("  status %s does not match the findings" % doc["status"]); sys.exit(1)

def sort_lines(src, dest):
    open(dest, "w").write("".join(sorted(open(src).readlines())))

def mutants(path, kind):
    doc = json.load(open(path))
    mod = next(iter(doc["metadata"]["modules"].values()))
    ops = mod["operators"]
    rules = sorted(f["rule"] for f in doc["findings"])
    if ops.get("relational") != 2 or ops.get("statement-deletion") != 1:
        print("  the guard's mutants are missing: %s" % ops); sys.exit(1)
    if kind == "killed":
        if rules or mod["survivors"] or mod["verdicts"]["survived"] != 0 or mod["verdicts"]["killed-assert"] < 4:
            print("  wanted every mutant killed by a failed check, got %s %s" % (rules, mod["verdicts"])); sys.exit(1)
    else:
        left = sorted(f["operator"] + ":" + f["replacement"] for f in doc["findings"] if f["rule"] == "survived-mutant")
        if rules != ["survived-mutant"] * 2 or left != ["relational:<=", "statement-deletion:(void)0"]:
            print("  wanted the boundary and the deleted guard to survive, got %s" % doc["findings"]); sys.exit(1)

def boundary(report):
    """the `<` -> `<=` mutant of the guard was killed by the CHECK_TRAPS test and by no other"""
    doc = json.load(open(report))
    found = [m for m in doc["mutants"] if m["operator"] == "relational" and m["replacement"] == "<="]
    if len(found) != 1:
        print("  no single boundary mutant: %s" % [m["id"] for m in found]); sys.exit(1)
    failed = []
    for run in found[0]["runs"].values():
        for line in run["results"].splitlines():
            row = json.loads(line)
            if row.get("status") == "fail":
                failed.append(row["id"])
    if failed != ["table/traps_at_cap"]:
        print("  the boundary mutant was killed by %s" % failed); sys.exit(1)

def same_meta(a, b):
    ma, mb = json.load(open(a))["metadata"], json.load(open(b))["metadata"]
    if ma != mb:
        print("  mutation results differ between the rounds"); sys.exit(1)

COMMANDS = {"collect": collect, "collect_modes": collect_modes, "mkfd": mkfd, "policy": policy, "levels": levels, "check": check, "good": good,
            "bad": bad, "gpolicy": gpolicy, "gcheck": gcheck, "sort": sort_lines, "mutants": mutants, "boundary": boundary, "same_meta": same_meta}
COMMANDS[sys.argv[1]](*sys.argv[2:])
PY
tool() { "${PY[@]}" "$out/tool.py" "$@"; }

# ---- the build files ----------------------------------------------------------------------------------------------
begin "rigor buckfiles accepts gate//rt:require for a library, a binary and a test, and no other gate label"
mkdir -p "$out/bf_ok" "$out/bf_other" "$out/bf_fuzz"
cat > "$out/bf_ok/BUCK" <<'EOF'
load("@gate//rules:c.bzl", "c_binary", "c_library", "c_test")

c_library(name = "a", srcs = ["a.c"], headers = ["a.h"], deps = ["gate//rt:require"])
c_binary(name = "b", srcs = ["b.c"], deps = [":a", "gate//rt:require"])
c_test(name = "t", srcs = ["t.c"], deps = [":a", "gate//rt:require"])
EOF
printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "a", srcs = ["a.c"], deps = ["gate//ctest:perf"])\n' > "$out/bf_other/BUCK"
printf 'load("@gate//rules:c.bzl", "c_fuzz")\n\nc_fuzz(name = "f", srcs = ["f.c"], deps = ["gate//rt:require"])\n' > "$out/bf_fuzz/BUCK"
for i in 1 2; do
  "${RIGOR[@]}" buckfiles --root "$out/bf_ok" --out "$out/bf_ok.$i.json" > "$out/bf_ok.$i.txt" 2>&1 || fail "$CUR: the dependency was refused" "$out/bf_ok.$i.txt"
  for d in bf_other bf_fuzz; do
    "${RIGOR[@]}" buckfiles --root "$out/$d" --out "$out/$d.$i.json" > "$out/$d.$i.txt" 2>&1 && fail "$CUR: $d was accepted" "$out/$d.$i.txt"
    grep -q '"rule":"bad-argument"' "$out/$d.$i.txt" || fail "$CUR: $d: no bad-argument finding" "$out/$d.$i.txt"
  done
done
for d in bf_ok bf_other bf_fuzz; do cmp -s "$out/$d.1.json" "$out/$d.2.json" || fail "$CUR: $d is not deterministic"; done
echo "  ok: accepted; other gate label and c_fuzz: bad-argument; identical twice"

# ---- one round: everything built and judged ----------------------------------------------------------------------
# round <n>: test results in both modes, facts in both modes, structure facts, libc list, mutation reports
# out_of <log> <target-fragment> -> path of that target's output file
out_of() { awk -v t="$2" 'index($1, t) && /buck-out/ {print $2}' "$1" | tail -1; }

round() {
  local n="$1" mode p t
  local d="$out/r$n"
  mkdir -p "$d/facts_release" "$d/facts_san"
  # results in each mode
  for mode in release san; do
    run "$d/res_$mode.log" build --target-platforms "toolchains//:linux_$mode" "$pkg:table_test_results" "$pkg:table_bad_results" --show-output \
      || fail "$CUR: results ($mode, round $n) did not build" "$d/res_$mode.log"
    for t in table_test table_bad; do
      p="$(out_of "$d/res_$mode.log" "$pkg:${t}_results")"
      [ -f "$p" ] || fail "$CUR: no results file for $t ($mode)" "$d/res_$mode.log"
      cp "$p" "$d/$t.$mode.jsonl"
    done
  done
  # facts, structure, libc list
  run "$d/facts_release.log" build "$pkg:table_facts" "$pkg:table_bin_facts" "$pkg:table_test_facts" "$pkg:own_trap_facts" "$pkg:bad_dep_facts" \
    "$pkg:own_header_facts" "$pkg:reserved_define_facts" "$pkg:reserved_decl_facts" "$pkg:reserved_addr_facts" \
    "$pkg:spoof_user_facts" "$pkg:guards_a_facts" "$pkg:guards_b_facts" "$pkg:guards_a_s" "$pkg:guards_b_s" \
    "$pkg:table_facts[calls]" "$pkg:table_bin_facts[calls]" "$pkg:table_test_facts[calls]" \
    //ctest:ctest_facts //rt:require_facts "$pkg:table_s" "$pkg:table_bin_s" toolchains//:libc_symbols --show-output \
    || fail "$CUR: facts (release, round $n) did not build" "$d/facts_release.log"
  tool collect "$d/facts_release.log" "$d/facts_release" facts
  tool collect_modes "$d/facts_release.log" "$d/mrel" ""
  tool collect "$d/facts_release.log" "$d/st" s
  p="$(out_of "$d/facts_release.log" libc_symbols)"; cp "$p" "$d/libc.symbols"
  run "$d/facts_san.log" build --target-platforms toolchains//:linux_san "$pkg:table_facts_san" "$pkg:table_bin_facts_san" "$pkg:table_test_facts_san" \
    "$pkg:own_trap_facts_san" "$pkg:bad_dep_facts_san" "$pkg:table_facts_san[calls]" "$pkg:table_bin_facts_san[calls]" \
    "$pkg:table_test_facts_san[calls]" //ctest:ctest_facts_san //rt:require_facts_san --show-output \
    || fail "$CUR: facts (san, round $n) did not build" "$d/facts_san.log"
  tool collect "$d/facts_san.log" "$d/facts_san" facts_san
  tool collect_modes "$d/facts_san.log" "$d/msan" "_san"
  # mutation reports
  run "$d/mut.log" build "$pkg:table_mutants" "$pkg:weak_mutants" --show-full-output || fail "$CUR: mutants (round $n) did not build" "$d/mut.log"
  mkdir -p "$d/mut_good" "$d/mut_weak"
  cp "$(out_of "$d/mut.log" "$pkg:table_mutants")" "$d/mut_good/table.json"
  cp "$(out_of "$d/mut.log" "$pkg:weak_mutants")" "$d/mut_weak/weak.json"
}

# gate_case <dir> <name> <gate> <want-exit> <policy> <facts-dir> -- <expected error>...
gate_case() {
  local d="$1" name="$2" gate="$3" want="$4" pol="$5" fd="$6"; shift 6
  [ "${1:-}" = "--" ] && shift
  local rc
  "${RIGOR[@]}" facts --gate "$gate" --facts "$fd" --policy "$pol" --libc "$d/libc.symbols" --out "$d/$name.$gate.json" > "$d/$name.$gate.txt" 2>&1
  rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name/$gate exited $rc, wanted $want" "$d/$name.$gate.txt"
  tool check "$d/$name.$gate.json" "$@" || fail "$CUR: $name/$gate findings differ" "$d/$name.$gate.txt"
  echo "  $name/$gate -> exit $rc ${*:-}"
}

check_results() {
  local d="$out/r$1" mode
  for mode in release san; do
    tool good "$d/table_test.$mode.jsonl" || fail "$CUR: table_test ($mode)"
    tool bad "$d/table_bad.$mode.jsonl" "$mode" || fail "$CUR: table_bad ($mode)"
    echo "  $mode: 3 passing tests; 8 failing tests, each with the reason that names what happened"
  done
}

check_gates() {
  local d="$out/r$1" mode fd g
  tool policy "$d/ok.toml" table table_bin table_test
  tool policy "$d/trap.toml" own_trap
  tool policy "$d/bad.toml" bad_dep
  for mode in release san; do
    fd="$d/facts_$mode"
    tool mkfd "$fd" "$d/fd_ok_$mode" table table_bin table_test ctest
    tool mkfd "$fd" "$d/fd_req_$mode" table table_bin table_test ctest require
    tool mkfd "$fd" "$d/fd_trap_$mode" own_trap ctest
    tool mkfd "$fd" "$d/fd_bad_$mode" bad_dep ctest
    # the symbols gate judges the release objects; the san objects carry the sanitizer's own symbols
    gate_case "$d" "ok_$mode" semantic-suppressions 0 "$d/ok.toml" "$d/fd_ok_$mode" --
    gate_case "$d" "req_$mode" semantic-suppressions 0 "$d/ok.toml" "$d/fd_req_$mode" --
    gate_case "$d" "trap_$mode" semantic-suppressions 1 "$d/trap.toml" "$d/fd_trap_$mode" -- "forbidden-builtin:__builtin_trap"
    if [ "$mode" = release ]; then
      gate_case "$d" "ok_$mode" symbols 0 "$d/ok.toml" "$d/fd_ok_$mode" --
      gate_case "$d" "req_$mode" symbols 0 "$d/ok.toml" "$d/fd_req_$mode" --
      gate_case "$d" "bad_$mode" symbols 1 "$d/bad.toml" "$d/fd_bad_$mode" -- "missing-dep-facts://ctest:perf"
    fi
  done
  # T131 (release facts; the scanner is the same in san): the gate-cell binding and the reserved name
  tool policy "$d/own.toml" own_header
  tool policy "$d/rdef.toml" reserved_define
  tool policy "$d/rdecl.toml" reserved_decl
  tool policy "$d/raddr.toml" reserved_addr
  tool policy "$d/spoof.toml" spoof_user
  tool mkfd "$d/facts_release" "$d/fd_spoof" spoof_user ctest require
  gate_case "$d" spoof_user semantic-suppressions 1 "$d/spoof.toml" "$d/fd_spoof" -- "reserved-identifier:#define rigor_require"
  tool mkfd "$d/facts_release" "$d/fd_own" own_header ctest require
  tool mkfd "$d/facts_release" "$d/fd_rdef" reserved_define ctest require
  tool mkfd "$d/facts_release" "$d/fd_rdecl" reserved_decl ctest require
  tool mkfd "$d/facts_release" "$d/fd_raddr" reserved_addr ctest require
  gate_case "$d" own_header semantic-suppressions 1 "$d/own.toml" "$d/fd_own" -- "forbidden-builtin:__builtin_trap"
  gate_case "$d" reserved_define semantic-suppressions 1 "$d/rdef.toml" "$d/fd_rdef" -- "reserved-identifier:#define rigor_require" "reserved-identifier:#undef rigor_require"
  gate_case "$d" reserved_decl semantic-suppressions 1 "$d/rdecl.toml" "$d/fd_rdecl" -- "reserved-identifier:rigor_require" "reserved-identifier:rigor_require"
  gate_case "$d" reserved_addr semantic-suppressions 1 "$d/raddr.toml" "$d/fd_raddr" -- "reserved-identifier:rigor_require"
  "${RIGOR[@]}" facts --modes "$d/mrel" "$d/msan" --out "$d/modes.json" > "$d/modes.txt" 2>&1 || fail "$CUR: mode-divergence" "$d/modes.txt"
  tool check "$d/modes.json" || fail "$CUR: mode-divergence findings"
  echo "  mode-divergence: PASS (the guard is the same code in release and san)"
}

check_structure() {
  local d="$out/r$1"
  tool levels "$d/st.toml" table table_bin
  tool mkfd "$d/st" "$d/st_t" table table_bin
  "${RIGOR[@]}" structure --facts "$d/st_t" --policy "$d/st.toml" --out "$d/structure.json" > "$d/structure.txt" 2>&1 || fail "$CUR: structure failed" "$d/structure.txt"
  tool check "$d/structure.json" || fail "$CUR: structure findings"
  echo "  structure: PASS (the guard's function in the gate's header is not the product's)"
}

# guards_case <name> <want-exit> <a> <b> -- <expected error>...: `rigor guards` on guards_a (6 sites, 130 lines, cap 3) and
# guards_b (2 sites, 130 lines, cap 3) with the budgets A and B
guards_case() {
  local d="$out/r$CURRENT" name="$1" want="$2" a="$3" b="$4" rc; shift 4
  [ "${1:-}" = "--" ] && shift
  tool gpolicy "$d/g_$name.toml" "$a" "$b"
  "${RIGOR[@]}" guards --facts "$d/fd_g" --structure "$d/st_g" --policy "$d/g_$name.toml" --out "$d/guards_$name.json" > "$d/guards_$name.txt" 2>&1
  rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: guards/$name exited $rc, wanted $want" "$d/guards_$name.txt"
  tool gcheck "$d/guards_$name.json" "$@" || fail "$CUR: guards/$name findings differ" "$d/guards_$name.txt"
  echo "  guards/$name (a=$a, b=$b) -> exit $rc ${*:-}"
}

check_guards() {
  local d="$out/r$1"
  CURRENT="$1"
  tool mkfd "$d/facts_release" "$d/fd_g" guards_a guards_b
  tool mkfd "$d/st" "$d/st_g" guards_a guards_b
  guards_case within 0 3 2 --
  guards_case none 0 0 0 --
  guards_case over_cap 1 4 0 -- guard-budget-over-cap:guards_a
  guards_case over_sites 1 0 3 -- guard-budget-over-sites:guards_b
}

check_mutants() {
  local d="$out/r$1"
  printf '[module."%s:table_mutants"]\nlevel = "L3"\n' "$pkg" > "$d/mut_good.toml"
  printf '[module."%s:weak_mutants"]\nlevel = "L3"\n' "$pkg" > "$d/mut_weak.toml"
  "${RIGOR[@]}" mutants --results "$d/mut_good" --policy "$d/mut_good.toml" --out "$d/mut_good.json" > "$d/mut_good.txt" 2>&1 \
    || fail "$CUR: the guard's mutants were not all killed" "$d/mut_good.txt"
  tool mutants "$d/mut_good.json" killed || fail "$CUR: mutants (CHECK_TRAPS tests)"
  tool boundary "$d/mut_good/table.json" || fail "$CUR: boundary mutant"
  "${RIGOR[@]}" mutants --results "$d/mut_weak" --policy "$d/mut_weak.toml" --out "$d/mut_weak.json" > "$d/mut_weak.txt" 2>&1 \
    && fail "$CUR: the module without CHECK_TRAPS tests passed" "$d/mut_weak.txt"
  tool mutants "$d/mut_weak.json" survived || fail "$CUR: mutants (no CHECK_TRAPS)"
  echo "  with CHECK_TRAPS: 5 mutants, none survives, the '<' -> '<=' boundary mutant is killed by traps_at_cap only"
  echo "  without CHECK_TRAPS: the boundary and the deleted guard survive (the zero-survivors rule)"
}

# ---- round 1 ------------------------------------------------------------------------------------------------------
begin "build both modes: test results, facts, structure facts and mutation reports on RE"
round 1
echo "  built; results, facts and reports collected"

begin "the tests, in release and san: what passes, what fails and why"
check_results 1

begin "rigor facts (semantic-suppressions, symbols) on the product in both modes; the red cases"
check_gates 1

begin "rigor structure on the product"
check_structure 1

begin "rigor guards: call sites, the declared budget within the cap, over the sites, over the cap"
check_guards 1

begin "mutation: the guard's mutants and the CHECK_TRAPS tests"
check_mutants 1

begin "no core file: the release test binaries, run here, leave none and give the same answer twice"
run "$out/bin.log" build "$pkg:table_test" "$pkg:table_bad" --show-output || fail "$CUR: binaries did not build" "$out/bin.log"
mkdir -p "$out/cwd"
for t in table_test table_bad; do
  bin="$root/$(out_of "$out/bin.log" "$pkg:$t")"
  [ -x "$bin" ] || fail "$CUR: no binary for $t" "$out/bin.log"
  for i in 1 2; do
    (cd "$out/cwd" && "$bin" --seed 1 --out "$out/$t.local.$i.jsonl" > "$out/$t.local.$i.txt" 2>&1)
  done
  cmp -s "$out/$t.local.1.jsonl" "$out/$t.local.2.jsonl" || fail "$CUR: $t is not deterministic locally"
done
tool good "$out/table_test.local.1.jsonl" || fail "$CUR: local table_test"
tool bad "$out/table_bad.local.1.jsonl" release || fail "$CUR: local table_bad"
if find "$out/cwd" -name 'core*' -type f 2> /dev/null | grep -q .; then fail "$CUR: a core file was left"; fi
echo "  no core file; the local runs agree with the farm's"

# ---- round 2: stamped sources, so that nothing can come from a cache ----------------------------------------------
begin "everything again from sources stamped with a nonce: identical results"
nonce="$(date +%s%N)-$$"
for f in "$scratch"/*.c; do sed -i "\$ s|\$| /* nonce $nonce */|" "$f"; done
round 2
check_results 2
check_gates 2
check_structure 2
check_guards 2
check_mutants 2
for mode in release san; do
  for t in table_test table_bad; do
    tool sort "$out/r1/$t.$mode.jsonl" "$out/r1/$t.$mode.sorted"
    tool sort "$out/r2/$t.$mode.jsonl" "$out/r2/$t.$mode.sorted"
    cmp -s "$out/r1/$t.$mode.sorted" "$out/r2/$t.$mode.sorted" || fail "$CUR: $t ($mode) differs between the rounds" "$out/r2/$t.$mode.sorted"
  done
done
for f in "$out"/r1/*.json; do
  name="$(basename "$f")"
  case "$name" in mut_*.json) continue ;; esac
  cmp -s "$f" "$out/r2/$name" || fail "$CUR: $name differs between the rounds" "$out/r2/$name"
done
tool same_meta "$out/r1/mut_good.json" "$out/r2/mut_good.json" || fail "$CUR: mutation results differ (good)"
tool same_meta "$out/r1/mut_weak.json" "$out/r2/mut_weak.json" || fail "$CUR: mutation results differ (weak)"
echo "  results, gate outputs and mutation verdicts are identical in both rounds"

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
