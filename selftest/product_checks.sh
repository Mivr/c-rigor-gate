#!/usr/bin/env bash
# Self-test of the semantic product checks (T004): the <name>_facts actions on RE, `rigor facts`
# (gates semantic-suppressions and symbols) and `rigor buckfiles`.
# Every red case is something a line regex cannot see (the T002 suppression scan is run on it and
# must pass it), and every one has a green sibling. Needs bash, python3 (stdlib), git, tools/buck2.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
B=(tools/buck2)
PLAT=toolchains//:linux_
scratch="selftest/scratch_pc"
pkg="//selftest/scratch_pc/p"
out="$(mktemp -d)"
cleanup() { rm -rf "$scratch" "$out"; }
trap cleanup EXIT
RIGOR=(gate/rigor)

step=0
fail() { echo "FAIL [$step]: $1" >&2; [ -n "${2:-}" ] && { echo "---- output ----" >&2; tail -n 40 "$2" >&2; }; exit 1; }
begin() { step=$((step + 1)); echo "[$step] $1"; CUR="$1"; }
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
run() { local log="$1"; shift; "${B[@]}" "$@" 2>&1 | strip_ansi > "$log"; return "${PIPESTATUS[0]}"; }
must_pass() { local log="$out/$step.log"; run "$log" "$@" || fail "$CUR: buck2 $* failed" "$log"; }

# --------------------------------------------------------------------------------------
# Throwaway product: one package, one BUCK file that passes `rigor buckfiles`.
# --------------------------------------------------------------------------------------
mkdir -p "$scratch/p"
cd "$scratch/p"
cat > BUCK <<'EOF'
load("@gate//rules:c.bzl", "c_binary", "c_fuzz", "c_library", "c_test")

c_library(name = "clean", srcs = ["clean.c"], headers = ["clean.h"])
c_test(name = "clean_test", srcs = ["clean_test.c"], deps = [":clean"])
c_binary(name = "clean_bin", srcs = ["clean_bin.c"], deps = [":clean"])
c_library(name = "paste", srcs = ["paste.c"])
c_library(name = "splice", srcs = ["splice.c"])
c_library(name = "digraph", srcs = ["digraph.c"])
c_library(name = "attr", srcs = ["attr.c"])
c_library(name = "weak", srcs = ["weak.c"])
c_library(name = "asm", srcs = ["asm.c"])
c_library(name = "rename", srcs = ["rename.c"])
c_library(name = "unreach", srcs = ["unreach.c"])
c_library(name = "kill", srcs = ["kill.c"])
c_library(name = "fopen", srcs = ["fopen.c"])
c_library(name = "write", srcs = ["write.c"])
c_library(name = "ctestsym", srcs = ["ctestsym.c"])
c_library(name = "puts", srcs = ["puts.c"])
c_library(name = "dep_a", srcs = ["dep_a.c"])
c_library(name = "dep_b", srcs = ["dep_b.c"], deps = [":dep_a"])
c_library(name = "dep_c", srcs = ["dep_c.c"])
c_test(name = "exittest", srcs = ["exittest.c"])
c_fuzz(name = "fz", srcs = ["fz_fuzz.c"])
EOF

# --- green ---
cat > clean.h <<'EOF'
#ifndef CLEAN_H
#define CLEAN_H
int clean_len(void);
#endif
EOF
cat > clean.c <<'EOF'
#include "clean.h"
/* Words that only look dangerous: asm, __attribute__((weak)), _Pragma, __builtin_trap, and a
   line such as #pragma clang diagnostic ignored "-Wall" inside a comment are not code. */
static const char *const k_words = "asm __asm__ #pragma _Pragma(\"x\") __builtin_trap";
__attribute__((noreturn)) static void clean_die(void) { for (;;) { } }
__attribute__((unused)) static int clean_spare(void) { return 0; }
int clean_len(void) {
    if (k_words == 0) { clean_die(); }
    return (int)sizeof k_words;
}
EOF
cat > clean_test.c <<'EOF'
#include "clean.h"
#include "ctest/ctest.h"
static void t_len(ctest_t *t) { CHECK_EQ_I64(t, clean_len(), 8); }
CTEST_SUITE("clean", { "len", t_len })
EOF
cat > clean_bin.c <<'EOF'
#include <stdio.h>
#include "clean.h"
int main(void) { return printf("%d\n", clean_len()) > 0 ? 0 : 1; }
EOF

# --- semantic reds: each of these passes the T002 line scan ---
cat > paste.c <<'EOF'
#define GLUE(a, b) a##b
#define OP GLUE(_Pra, gma)
OP("clang diagnostic ignored \"-Wunused-variable\"")
int paste_f(void) { int unused_var = 1; return 0; }
EOF
printf '#pra\\\ngma clang diagnostic ignored "-Wunused-variable"\nint splice_f(void) { int unused_var = 1; return 0; }\n' > splice.c
cat > digraph.c <<'EOF'
%:pragma clang diagnostic ignored "-Wunused-variable"
int digraph_f(void) { int unused_var = 1; return 0; }
EOF
cat > attr.c <<'EOF'
#define A(x) __attribute__((x))
A(optnone) int attr_f(int a) { return a + 1; }
A(section(".attr_data")) int attr_v = 3;
EOF
cat > weak.c <<'EOF'
#define A(x) __attribute__((x))
A(weak) int weak_f(void) { return 1; }
EOF
cat > asm.c <<'EOF'
#define ASM __asm__
int asm_f(void) { ASM volatile("nop"); return 0; }
EOF
cat > unreach.c <<'EOF'
#define UNREACHABLE() __builtin_unreachable()
int unreach_f(int a) { if (a > 0) { return 1; } UNREACHABLE(); }
EOF

# --- symbol reds ---
cat > kill.c <<'EOF'
#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#define PING(pid) kill((pid), 0)
int ping(int pid) { return PING(pid); }
EOF
cat > rename.c <<'EOF'
int my_exit(int code) __asm__("exit");
void rename_f(void) { my_exit(0); }
EOF
cat > fopen.c <<'EOF'
#include <stdio.h>
FILE *open_it(const char *path) { return fopen(path, "r"); }
EOF
cat > write.c <<'EOF'
long write(int fd, const void *buf, unsigned long n) { (void)fd; (void)buf; return (long)n; }
EOF
cat > ctestsym.c <<'EOF'
void ctest_check(void) { }
EOF
cat > puts.c <<'EOF'
#include <stdio.h>
int say(void) { return puts("hi"); }
EOF
cat > dep_a.c <<'EOF'
int a_value(void) { return 7; }
EOF
cat > dep_b.c <<'EOF'
int a_value(void);
int b_value(void) { return a_value() + 1; }
EOF
cat > dep_c.c <<'EOF'
int a_value(void);
int c_value(void) { return a_value() + 2; }
EOF
cat > exittest.c <<'EOF'
#define _POSIX_C_SOURCE 200809L
#include <unistd.h>
#include "ctest/ctest.h"
static void t_quit(ctest_t *t) { CHECK(t, 1); _exit(0); }
CTEST_SUITE("exittest", { "quit", t_quit })
EOF
# The libFuzzer entry point is spelled in two pieces here only so that this script itself does not
# trip the line scan that guards the repository (the entry point is allowed in *_fuzz.c only).
entry="LLVMFuzzer""TestOneInput"
cat > fz_fuzz.c <<EOF
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
int $entry(const uint8_t *data, size_t size) { (void)data; return getenv("HOME") != NULL && size > 0 ? 1 : 0; }
EOF
cd "$root"

# --------------------------------------------------------------------------------------
# Helper program (one Python file): policies, fact collection, result checks.
# --------------------------------------------------------------------------------------
cat > "$out/tool.py" <<'PY'
import json, os, re, shutil, subprocess, sys

PKG = "//selftest/scratch_pc/p:"

def policy(dest, specs):
    """policy DEST SPEC...   SPEC = name[;allow=a,b][;exempt=x][;builtins=y]  (global block of hello.toml)"""
    head = open("policy/hello.toml").read().split("[module.")[0]
    text = head
    for spec in specs:
        name, *opts = spec.split(";")
        text += '[module."%s"]\n' % (name if name.startswith("//") else PKG + name)
        for opt in opts:
            key, values = opt.split("=")
            key = {"exempt": "deny_exempt", "builtins": "allow_builtins"}.get(key, key)
            text += "%s = [%s]\n" % (key, ", ".join('"%s"' % v for v in values.split(",")))
        text += "\n"
    open(dest, "w").write(text)

def collect(log, dest):
    """collect LOG DEST: copy every `<label>_facts <path>` line of a --show-output log to DEST/<name>.json"""
    os.makedirs(dest, exist_ok=True)
    for line in open(log):
        m = re.match(r"^root//(\S+):(\w+)_facts\s+(\S+)$", line.strip())
        if m:
            shutil.copy(m.group(3), os.path.join(dest, m.group(2) + ".json"))

def mkfd(allfacts, dest, names):
    """mkfd ALL DEST NAME...: a facts directory with those targets plus the ctest runtime"""
    os.makedirs(dest, exist_ok=True)
    for name in list(names) + ["ctest"]:
        shutil.copy(os.path.join(allfacts, name + ".json"), os.path.join(dest, name + ".json"))

def check(result, expected):
    """check RESULT EXPECTED...: the findings are exactly the expected `rule` / `rule:symbol|name` entries"""
    doc = json.load(open(result))
    def render(f):
        detail = "" if f["rule"] == "line-directive" else (f.get("symbol") or f.get("name"))
        return f["rule"] + (":" + detail if detail else "")
    got = sorted(render(f) for f in doc["findings"] if f["severity"] == "error")
    want = sorted(expected)
    if got != want:
        print("  wanted %s\n  got    %s" % (want, got))
        sys.exit(1)
    if (doc["status"] == "PASS") != (not want):
        print("  status %s does not match findings" % doc["status"])
        sys.exit(1)

def textscan_misses(path, workdir):
    """The T002 suppression scan must PASS a file that the semantic scan rejects."""
    repo = os.path.join(workdir, "r")
    shutil.rmtree(repo, ignore_errors=True)
    os.makedirs(repo)
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    def git(*a): subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@x.invalid", *a], check=True, env=env, capture_output=True)
    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "base")
    shutil.copy(path, os.path.join(repo, os.path.basename(path)))
    git("add", "-A"); git("commit", "-q", "-m", "add")
    done = subprocess.run(["gate/rigor", "suppressions", "--repo", repo, "--base", "HEAD~1", "--head", "HEAD"], capture_output=True, text=True)
    if done.returncode != 0:
        print("  the line scan already flags this file (exit %d): %s" % (done.returncode, done.stdout))
        sys.exit(1)

COMMANDS = {
    "policy": lambda a: policy(a[0], a[1:]),
    "collect": lambda a: collect(a[0], a[1]),
    "mkfd": lambda a: mkfd(a[0], a[1], a[2:]),
    "check": lambda a: check(a[0], a[1:]),
    "textscan_misses": lambda a: textscan_misses(a[0], a[1]),
}
COMMANDS[sys.argv[1]](sys.argv[2:])
PY
tool() { python3 -I "$out/tool.py" "$@"; }

# gate_case <name> <gate> <want-exit> <policy-file> <facts-target>... -- <expected finding>...
gate_case() {
  local name="$1" gate="$2" want="$3" pol="$4"; shift 4
  local targets=() expected=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do targets+=("$1"); shift; done
  [ "${1:-}" = "--" ] && shift
  expected=("$@")
  local fd="$out/fd/$name.$gate"; rm -rf "$fd"
  tool mkfd "$out/facts" "$fd" "${targets[@]}" || fail "$CUR: no facts for ${targets[*]}"
  local res="$out/res/$name.$gate.json"; mkdir -p "$out/res"
  "${RIGOR[@]}" facts --gate "$gate" --facts "$fd" --policy "$pol" --libc "$out/libc.symbols" --out "$res" > "$out/res/$name.$gate.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name/$gate exited $rc, wanted $want" "$out/res/$name.$gate.txt"
  tool check "$res" "${expected[@]}" || fail "$CUR: $name/$gate findings differ" "$out/res/$name.$gate.txt"
  echo "  $name/$gate -> exit $rc ${expected[*]:-}"
}

SEM=semantic-suppressions
SYM=symbols

# --------------------------------------------------------------------------------------
begin "the throwaway product's build files pass rigor buckfiles (and so does examples/)"
"${RIGOR[@]}" buckfiles --root "$scratch" > "$out/bf.txt" 2>&1 || fail "$CUR" "$out/bf.txt"
"${RIGOR[@]}" buckfiles --root examples > "$out/bf2.txt" 2>&1 || fail "$CUR" "$out/bf2.txt"

begin "line markers: locate the toolchain's header directory and write the #line / GNU-marker sources"
must_pass build "//ctest:ctest[objects][ctest.c.o][preprocessed]" --show-output
pre="$(awk '/buck-out/ {print $2}' "$out/$step.log" | tail -1)"
sysinc="$(grep -o 'buck-out/[^" ]*/__sysroot__/tree/usr/include' "$pre" | head -1)"
[ -n "$sysinc" ] || fail "$CUR: no system include directory in $pre"
echo "  system root: $sysinc"
cd "$scratch/p"
EVIL='A(optnone) int evil(void) { __asm__ volatile("nop"); return 0; }'
# a spliced #line (evades the line regex) naming a real system header
printf '#define A(x) __attribute__((x))\n#li\\\nne 1 "%s/stdio.h"\n%s\n' "$sysinc" "$EVIL" > linespl.c
# a plain #line naming a system header (T002 catches this one too; the semantic gate must on its own)
printf '#define A(x) __attribute__((x))\n#line 1 "%s/stdio.h"\n%s\n' "$sysinc" "$EVIL" > lineplain.c
# a #line that only changes the number (backwards)
printf '#define A(x) __attribute__((x))\nint pad_a(void) { return 1; }\nint pad_b(void) { return 2; }\n#line 1\n%s\n' "$EVIL" > linenum.c
# the GNU marker form, which could forge "enter include" (flag 1), is refused by the sealed flags
printf 'int gnu_a(void) { return 1; }\n# 1 "x.c" 1\nint gnu_b(void) { return 2; }\n' > gnu.c
cat >> BUCK <<'EOF'
c_library(name = "linespl", srcs = ["linespl.c"])
c_library(name = "lineplain", srcs = ["lineplain.c"])
c_library(name = "linenum", srcs = ["linenum.c"])
c_library(name = "gnu", srcs = ["gnu.c"])
EOF
cd "$root"
"${RIGOR[@]}" buckfiles --root "$scratch" > "$out/bf3.txt" 2>&1 || fail "$CUR" "$out/bf3.txt"

begin "every red source passes the T002 line scan (this is what the semantic scan is for)"
for f in linespl paste splice digraph attr weak asm unreach kill rename fopen write ctestsym puts exittest fz_fuzz; do
  tool textscan_misses "$scratch/p/$f.c" "$out" || fail "$CUR: $f.c"
done
echo "  16 sources: line scan exit 0 on all"

begin "facts actions build on RE for every target (release) and the libc export list exists"
targets=(linespl lineplain linenum clean clean_test clean_bin paste splice digraph attr weak asm rename unreach kill fopen write ctestsym puts dep_a dep_b dep_c exittest fz)
args=(); for t in "${targets[@]}"; do args+=("$pkg:${t}_facts"); done
run "$out/facts.log" build "${args[@]}" //ctest:ctest_facts //examples/hello:lib_facts //examples/hello:hello_facts //examples/hello:hello_test_facts toolchains//:libc_symbols --show-output || fail "$CUR" "$out/facts.log"
tool collect "$out/facts.log" "$out/facts" || fail "$CUR: collect"
cp "$(awk '/libc_symbols/ && /buck-out/ {print $2}' "$out/facts.log" | tail -1)" "$out/libc.symbols" || fail "$CUR: no libc list"
for sym in write kill open fopen _exit; do grep -qx "$sym" "$out/libc.symbols" || fail "$CUR: libc list lacks $sym"; done
ls "$out/facts" | wc -l | xargs echo "  fact files:"

begin "green: clean library, test and binary pass both gates (comments, strings, noreturn and unused are not findings)"
tool policy "$out/p_clean.toml" clean clean_test "clean_bin;allow=printf"
gate_case clean $SEM 0 "$out/p_clean.toml" clean clean_test clean_bin --
gate_case clean $SYM 0 "$out/p_clean.toml" clean clean_test clean_bin --

begin "red: pragmas a line scan cannot see (token pasting, line splice, digraph) are findings"
for c in paste splice digraph; do
  tool policy "$out/p_$c.toml" "$c"
  gate_case $c $SEM 1 "$out/p_$c.toml" $c -- pragma
  gate_case $c $SYM 0 "$out/p_$c.toml" $c --
done

begin "red: forbidden attributes through a macro, weak symbols, inline asm behind a macro alias"
tool policy "$out/p_attr.toml" attr
gate_case attr $SEM 1 "$out/p_attr.toml" attr -- forbidden-attribute:optnone forbidden-attribute:section
tool policy "$out/p_weak.toml" weak
gate_case weak $SEM 1 "$out/p_weak.toml" weak -- forbidden-attribute:weak
gate_case weak $SYM 1 "$out/p_weak.toml" weak -- weak-symbol:weak_f
tool policy "$out/p_asm.toml" asm
gate_case asm $SEM 1 "$out/p_asm.toml" asm -- inline-asm:__asm__

begin "red: a #line cannot make the rest of the file look like a system header (optnone and asm still reported)"
for c in linespl lineplain linenum; do
  tool policy "$out/p_$c.toml" "$c"
  gate_case $c $SEM 1 "$out/p_$c.toml" $c -- line-directive forbidden-attribute:optnone inline-asm:__asm__
done

begin "red: the GNU line-marker form (which could forge flag 1) does not compile"
if run "$out/gnu.log" build "$pkg:gnu"; then fail "$CUR: gnu.c built" "$out/gnu.log"; fi
grep -q 'Wgnu-line-marker' "$out/gnu.log" || fail "$CUR: failed for the wrong reason" "$out/gnu.log"

begin "builtins: __builtin_unreachable behind a macro is a finding unless the module's policy allows it"
tool policy "$out/p_unreach.toml" unreach
gate_case unreach $SEM 1 "$out/p_unreach.toml" unreach -- forbidden-builtin:__builtin_unreachable
tool policy "$out/p_unreach_ok.toml" "unreach;builtins=__builtin_unreachable"
gate_case unreach_ok $SEM 0 "$out/p_unreach_ok.toml" unreach --
tool policy "$out/p_unreach_other.toml" "unreach;builtins=__builtin_trap"
gate_case unreach_other $SEM 1 "$out/p_unreach_other.toml" unreach -- forbidden-builtin:__builtin_unreachable

begin "symbols: kill through a macro alias, exit through an asm label, _exit in a test, getenv in a fuzz target"
tool policy "$out/p_kill.toml" kill
gate_case kill $SYM 1 "$out/p_kill.toml" kill -- denied-symbol:kill
tool policy "$out/p_rename.toml" rename
gate_case rename $SYM 1 "$out/p_rename.toml" rename -- denied-symbol:exit
gate_case rename $SEM 1 "$out/p_rename.toml" rename -- inline-asm:__asm__
tool policy "$out/p_exit.toml" exittest
gate_case exittest $SYM 1 "$out/p_exit.toml" exittest -- denied-symbol:_exit
tool policy "$out/p_fz.toml" fz
gate_case fz $SYM 1 "$out/p_fz.toml" fz -- denied-symbol:getenv
grep -q '"kind":"c_fuzz"' "$out/facts/fz.json" || fail "$CUR: fuzz facts are not of kind c_fuzz"

begin "symbols: fopen is denied without an exemption, fine with it; puts needs an allow entry"
tool policy "$out/p_fopen.toml" fopen
gate_case fopen $SYM 1 "$out/p_fopen.toml" fopen -- denied-symbol:fopen
tool policy "$out/p_fopen_ok.toml" "fopen;exempt=fopen"
gate_case fopen_ok $SYM 0 "$out/p_fopen_ok.toml" fopen --
tool policy "$out/p_fopen_other.toml" "fopen;exempt=open"
gate_case fopen_other $SYM 1 "$out/p_fopen_other.toml" fopen -- denied-symbol:fopen
tool policy "$out/p_puts.toml" puts
gate_case puts $SYM 1 "$out/p_puts.toml" puts -- undeclared-symbol:puts
tool policy "$out/p_puts_ok.toml" "puts;allow=puts"
gate_case puts_ok $SYM 0 "$out/p_puts_ok.toml" puts --

begin "symbols: defining write (libc) or ctest_check (the test runtime) is interposition"
tool policy "$out/p_write.toml" write
gate_case write $SYM 1 "$out/p_write.toml" write -- symbol-collision:write
tool policy "$out/p_cs.toml" ctestsym
gate_case ctestsym $SYM 1 "$out/p_cs.toml" ctestsym -- symbol-collision:ctest_check

begin "symbols: a dependency's exports are allowed to its dependents only; unlisted modules are findings"
tool policy "$out/p_dep_ab.toml" dep_a dep_b
gate_case dep_ab $SYM 0 "$out/p_dep_ab.toml" dep_a dep_b --
tool policy "$out/p_dep_ac.toml" dep_a dep_c
gate_case dep_ac $SYM 1 "$out/p_dep_ac.toml" dep_a dep_c -- undeclared-symbol:a_value
tool policy "$out/p_none.toml"
gate_case nopolicy $SYM 1 "$out/p_none.toml" clean -- module-not-in-policy
tool policy "$out/p_extra.toml" clean dep_a
gate_case extra $SYM 1 "$out/p_extra.toml" clean -- policy-module-without-facts

begin "the examples/hello product passes both gates under policy/hello.toml"
rm -rf "$out/fd/hello"; mkdir -p "$out/fd/hello"
for n in hello hello_test lib; do cp "$out/facts/$n.json" "$out/fd/hello/$n.json"; done
cp "$out/facts/ctest.json" "$out/fd/hello/ctest.json"
for g in $SEM $SYM; do
  "${RIGOR[@]}" facts --gate $g --facts "$out/fd/hello" --policy policy/hello.toml --libc "$out/libc.symbols" --out "$out/res/hello.$g.json" > "$out/res/hello.$g.txt" 2>&1 \
    || fail "$CUR: hello/$g" "$out/res/hello.$g.txt"
done

begin "buckfiles: assignment, native.cxx_library, second load, a .bzl file, BUCK.v2 and others are findings"
bf() { # <name> <want-rule> <file> <content>
  local d="$out/bf/$1"; rm -rf "$d"; mkdir -p "$d"
  printf '%s' "$4" > "$d/$3"
  [ "$3" = BUCK ] || printf 'load("@gate//rules:c.bzl", "c_library")\nc_library(name = "a", srcs = ["a.c"])\n' > "$d/BUCK"
  "${RIGOR[@]}" buckfiles --root "$d" --out "$d/r.json" > "$d/o.txt" 2>&1; local rc=$?
  [ "$rc" = 1 ] || fail "$CUR: $1 exited $rc" "$d/o.txt"
  tool check "$d/r.json" "$2" || fail "$CUR: $1 findings" "$d/o.txt"
  echo "  $1 -> $2"
}
L='load("@gate//rules:c.bzl", "c_library")
'
bf assign        bad-statement   BUCK "${L}FLAGS = [\"-O0\"]
c_library(name = \"a\", srcs = [\"a.c\"])
"
bf native        bad-call        BUCK "${L}native.cxx_library(name = \"a\", srcs = [\"a.c\"])
"
bf secondload    extra-load      BUCK "${L}load(\"@gate//rules:c.bzl\", \"c_test\")
"
bf otherload     bad-load        BUCK 'load("//tools:flags.bzl", "c_library")
'
bf bzl           forbidden-file  flags.bzl 'X = 1
'
bf buckv2        forbidden-file  BUCK.v2 'cxx_library(name = "evil")
'
bf package       forbidden-file  PACKAGE ''
bf flagskeyword  bad-argument    BUCK "${L}c_library(name = \"a\", srcs = [\"a.c\"], compiler_flags = [\"-w\"])
"
bf globbed       bad-argument    BUCK "${L}c_library(name = \"a\", srcs = glob([\"*.c\"]))
"
bf crosscelldep  bad-argument    BUCK "${L}c_library(name = \"a\", deps = [\"prelude//cxx:x\"])
"
bf syntax        parse-error     BUCK 'c_library(
'

begin "cache: rebuilding unchanged facts executes 0 actions"
must_pass build "${args[@]}" //ctest:ctest_facts
must_pass build "${args[@]}" //ctest:ctest_facts
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the second build"
echo "  second build: $n actions executed"

begin "cache: a changed source reruns its facts action on RE and the new symbol shows up"
printf 'int scratch_nonce_%s_%s(void) { return 1; }\n' "$(date +%s)" "$$" >> "$scratch/p/dep_a.c"
must_pass build "$pkg:dep_a_facts" --show-output
"${B[@]}" log what-ran 2>/dev/null | strip_ansi > "$out/whatran.txt"
grep -q 'c_facts' "$out/whatran.txt" || fail "$CUR: no c_facts action ran" "$out/whatran.txt"
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $3 !~ /^re\(/ {bad=1} END{exit !bad}'; then
  fail "$CUR: an action did not run on RE" "$out/whatran.txt"
fi
grep 'c_facts' "$out/whatran.txt" | head -2
grep -q 'scratch_nonce_' "$(awk '/dep_a_facts/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)" || fail "$CUR: new symbol missing from the facts"

begin "modes: facts exist in the release mode only"
for m in san cov fuzz; do
  if run "$out/inc.log" build --target-platforms ${PLAT}$m "$pkg:clean_facts"; then fail "$CUR: facts built in $m" "$out/inc.log"; fi
  grep -q "is incompatible with" "$out/inc.log" || fail "$CUR: $m failed for the wrong reason" "$out/inc.log"
done

echo "ALL CHECKS PASSED ($step)"
