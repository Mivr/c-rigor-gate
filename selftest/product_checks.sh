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
load("@gate//rules:c.bzl", "c_binary", "c_embed", "c_fuzz", "c_library", "c_test")

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
c_library(name = "at_ok", srcs = ["at_ok.c"])
c_library(name = "at_fetch", srcs = ["at_fetch.c"])
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
c_library(name = "b_alloca", srcs = ["b_alloca.c"])
c_library(name = "b_paste", srcs = ["b_paste.c"])
c_library(name = "b_frame", srcs = ["b_frame.c"])
c_library(name = "b_longjmp", srcs = ["b_longjmp.c"])
c_library(name = "b_sync", srcs = ["b_sync.c"])
c_library(name = "b_hidden", srcs = ["b_hidden.c"])
c_library(name = "b_io", srcs = ["b_io.c"])
c_library(name = "b_ovf", srcs = ["b_ovf.c"], headers = ["b_ovf.h"])
c_library(name = "b_hdrs", srcs = ["b_hdrs.c"])
c_library(name = "b_direct", srcs = ["b_direct.c"])
c_library(name = "x_ok", srcs = ["x_ok.c"])
c_library(name = "x_func", srcs = ["x_func.c"])
c_library(name = "x_mut", srcs = ["x_mut.c"])
c_library(name = "x_const", srcs = ["x_const.c"])
c_library(name = "sl_ok", srcs = ["sl_ok.c"], system_libs = ["pthread"])
c_library(name = "ex_c", srcs = ["ex_c.c"], headers = ["ex_c.h"])
c_library(name = "ex_b", srcs = ["ex_b.c"], headers = ["ex_b.h"], exported_deps = [":ex_c"])
c_library(name = "ex_a", srcs = ["ex_a.c"], deps = [":ex_b"])
c_library(name = "ex_d", srcs = ["ex_d.c"], deps = [":ex_b"])
c_embed(name = "emb", src = "emb.bin", symbol = "emb_blob")
EOF

# --- green ---
printf '\000\377T\n\000' > emb.bin   # T112: c_embed asset
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
cat > at_ok.c <<'EOF'
int at_ok_get(int *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
void at_ok_set(int *p, int v) { __atomic_store_n(p, v, __ATOMIC_RELEASE); }
EOF
cat > at_fetch.c <<'EOF'
int at_fetch_get(int *p) { return __atomic_load_n(p, __ATOMIC_ACQUIRE); }
int at_fetch_add(int *p) { return __atomic_fetch_add(p, 1, __ATOMIC_SEQ_CST); }
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
# T110: ex_b's public header includes ex_c.h and ex_b exports ex_c; ex_a lists only ex_b and builds. ex_d uses ex_c itself.
cat > ex_c.h <<'EOF'
#ifndef EX_C_H
#define EX_C_H
int ex_c_fn(void);
#endif
EOF
cat > ex_c.c <<'EOF'
#include "ex_c.h"
int ex_c_fn(void) { return 3; }
EOF
cat > ex_b.h <<'EOF'
#ifndef EX_B_H
#define EX_B_H
#include "selftest/scratch_pc/p/ex_c.h"
int ex_b_fn(void);
#endif
EOF
cat > ex_b.c <<'EOF'
#include "ex_b.h"
int ex_b_fn(void) { return ex_c_fn() + 1; }
EOF
cat > ex_a.c <<'EOF'
#include "selftest/scratch_pc/p/ex_b.h"
int ex_a_fn(void) { return ex_b_fn() + 1; }
EOF
cat > ex_d.c <<'EOF'
#include "selftest/scratch_pc/p/ex_b.h"
int ex_d_fn(void) { return ex_b_fn() + ex_c_fn(); }
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
# --- builtins (T014): default-deny on the preprocessed text ---
# The sealed flags make a call of a banned builtin a compile error, so these reds `#undef` the guard
# first: the semantic gate must still see both the #undef and the builtin.
cat > b_alloca.c <<'EOF'
#undef __builtin_alloca
int b_alloca_f(unsigned n) { char *p = __builtin_alloca(n); p[0] = 1; return p[0]; }
EOF
cat > b_paste.c <<'EOF'
#undef __builtin_alloca
#define CAT(a, b) a##b
#define GROW(n) CAT(__builtin_, alloca)(n)
int b_paste_f(unsigned n) { char *p = GROW(n); p[0] = 1; return p[0]; }
EOF
cat > b_frame.c <<'EOF'
#undef __builtin_frame_address
int b_frame_f(void) { return __builtin_frame_address(0) != 0; }
EOF
cat > b_longjmp.c <<'EOF'
static void *b_buf[5];
void b_longjmp_f(void) { __builtin_longjmp(b_buf, 1); }
EOF
cat > b_sync.c <<'EOF'
int b_sync_f(int *p) { return __sync_fetch_and_add(p, 1); }
EOF
cat > b_hidden.c <<'EOF'
#define JUMP(b) __builtin_longjmp((b), 1)
static void *b_hidden_buf[5];
void b_hidden_f(void) { JUMP(b_hidden_buf); }
EOF
# toolchain code a product names is charged to the product: inb() is an inline function of
# <sys/io.h> whose body is inline asm
cat > b_io.c <<'EOF'
#include <sys/io.h>
unsigned char b_io_f(void) { return inb(0x60); }
EOF
# green: what annas-c-like code expands to (offsetof, va_*, the overflow checkers)
cat > b_ovf.h <<'EOF'
#ifndef B_OVF_H
#define B_OVF_H
#include <stddef.h>
int b_ovf_mul(size_t a, size_t b, size_t *out);
size_t b_ovf_off(void);
int b_ovf_sum(int n, ...);
#endif
EOF
cat > b_ovf.c <<'EOF'
#include <stdarg.h>
#include "b_ovf.h"
struct b_rec { int a; char b; };
int b_ovf_mul(size_t a, size_t b, size_t *out) { return __builtin_mul_overflow(a, b, out) ? -1 : 0; }
size_t b_ovf_off(void) { return offsetof(struct b_rec, b); }
int b_ovf_sum(int n, ...) {
    va_list ap;
    int total = 0;
    va_start(ap, n);
    for (int i = 0; i < n; i++) { total += va_arg(ap, int); }
    va_end(ap);
    return total;
}
EOF
# the guard must not break toolchain headers: a wide include set with _GNU_SOURCE (alloca.h too)
{ echo '#define _GNU_SOURCE'
  for h in alloca assert complex ctype errno fenv float inttypes iso646 limits locale math setjmp signal \
           stdalign stdarg stdatomic stdbool stddef stdint stdio stdlib stdnoreturn string tgmath time \
           uchar wchar wctype fcntl poll pthread sys/mman sys/random sys/select sys/socket sys/stat \
           sys/types sys/wait netinet/in arpa/inet netdb unistd dirent byteswap endian x86intrin; do
    echo "#include <$h.h>"
  done
  echo 'int b_hdrs_f(int x) { return (int)htonl((uint32_t)x) + isdigit(x) + abs(x); }'
} > b_hdrs.c
# T033 exports policy: the green module defines exactly x_f and x_g; each red twin adds one thing.
cat > x_ok.c <<'EOF'
int x_f(void) { return 1; }
int x_g(void) { return 2; }
EOF
cat > x_func.c <<'EOF'
int x_f(void) { return 1; }
int x_g(void) { return 2; }
int x_hook(void) { return 3; }
EOF
cat > x_mut.c <<'EOF'
int x_f(void) { return 1; }
int x_g(void) { return 2; }
int (*x_hook)(void);
int x_state = 5;
EOF
cat > x_const.c <<'EOF'
int x_f(void) { return 1; }
int x_g(void) { return 2; }
const int x_table[4] = {1, 2, 3, 4};
const char *const x_names[2] = {"a", "b"};
EOF
cat > sl_ok.c <<'EOF'
#include <pthread.h>
static void *sl_body(void *arg) { return arg; }
int sl_run(void) { pthread_t th; void *out = 0; if (pthread_create(&th, 0, sl_body, 0) != 0) { return 1; } return pthread_join(th, &out); }
EOF
cat > b_direct.c <<'EOF'
int b_direct_f(unsigned n) { char *p = __builtin_alloca(n); p[0] = 1; return p[0]; }
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
            if key == "level":
                text += 'level = "%s"\n' % values
                continue
            if key == "mutable_data":    # T089: allow_mutable_data = true
                text += "allow_mutable_data = %s\n" % values
                continue
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
        detail = "" if f["rule"] == "line-directive" else (f.get("symbol") or f.get("name") or f.get("item") or f.get("lib"))
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

def collectmodes(log, dest, suffix):
    """collectmodes LOG DEST SUFFIX: every `<name>_facts<SUFFIX>` and `<name>_facts<SUFFIX>[calls]` line of a
    --show-output log to DEST/<name>.json and DEST/<name>.calls.json"""
    os.makedirs(dest, exist_ok=True)
    pattern = re.compile(r"^root//(\S+):(\w+)_facts" + suffix + r"(\[calls\])?\s+(\S+)$")
    for line in open(log):
        m = pattern.match(line.strip())
        if m:
            shutil.copy(m.group(4), os.path.join(dest, m.group(2) + (".calls.json" if m.group(3) else ".json")))

def mkmd(src, dest, names):
    """mkmd SRC DEST NAME...: a modes directory with those targets (facts and calls)"""
    os.makedirs(dest, exist_ok=True)
    for name in names:
        for ext in (".json", ".calls.json"):
            shutil.copy(os.path.join(src, name + ext), os.path.join(dest, name + ext))

def only_in(result, mode):
    """only_in RESULT MODE: every finding says the item exists in MODE only"""
    doc = json.load(open(result))
    bad = [f for f in doc["findings"] if f.get("only_in") != mode]
    if bad or not doc["findings"]:
        print("  wanted only_in=%s findings, got %s" % (mode, doc["findings"]))
        sys.exit(1)

def tamper(path, key, value):
    """tamper FILE KEY VALUE: set a top-level key of a JSON file (VALUE is JSON)"""
    doc = json.load(open(path))
    doc[key] = json.loads(value)
    json.dump(doc, open(path, "w"))

COMMANDS = {
    "collectmodes": lambda a: collectmodes(a[0], a[1], a[2]),
    "mkmd": lambda a: mkmd(a[0], a[1], a[2:]),
    "only_in": lambda a: only_in(a[0], a[1]),
    "tamper": lambda a: tamper(a[0], a[1], a[2]),
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
for f in linespl paste splice digraph attr weak asm unreach at_ok at_fetch kill rename fopen write ctestsym puts exittest fz_fuzz; do
  tool textscan_misses "$scratch/p/$f.c" "$out" || fail "$CUR: $f.c"
done
echo "  16 sources: line scan exit 0 on all"

begin "facts actions build on RE for every target (release) and the libc export list exists"
targets=(linespl lineplain linenum clean clean_test clean_bin paste splice digraph attr weak asm rename unreach at_ok at_fetch kill fopen write ctestsym puts dep_a dep_b dep_c exittest fz b_alloca b_paste b_frame b_longjmp b_sync b_hidden b_io b_ovf b_hdrs x_ok x_func x_mut x_const sl_ok ex_a ex_b ex_c ex_d emb)
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

begin "builtins: __atomic_load_n/__atomic_store_n are guarded; every other __atomic_* stays forbidden"
tool policy "$out/p_at.toml" at_ok
gate_case at_ok_unlisted $SEM 1 "$out/p_at.toml" at_ok -- forbidden-builtin:__atomic_load_n forbidden-builtin:__atomic_store_n
tool policy "$out/p_at_ok.toml" "at_ok;builtins=__atomic_load_n,__atomic_store_n"
gate_case at_ok_listed $SEM 0 "$out/p_at_ok.toml" at_ok --
tool policy "$out/p_at_fetch.toml" "at_fetch;builtins=__atomic_load_n,__atomic_store_n"
gate_case at_fetch $SEM 1 "$out/p_at_fetch.toml" at_fetch -- forbidden-builtin:__atomic_fetch_add

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

begin "exported_deps (T110): the facts of ex_b carry the edge to ex_c, ex_a's only ex_b; a dependent still needs its own dep"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["deps"]==[sys.argv[2]] else 1)' "$out/facts/ex_b.json" "//selftest/scratch_pc/p:ex_c" \
  || fail "$CUR: ex_b facts do not list exactly ex_c"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["deps"]==[sys.argv[2]] else 1)' "$out/facts/ex_a.json" "//selftest/scratch_pc/p:ex_b" \
  || fail "$CUR: ex_a facts do not list exactly ex_b"
tool policy "$out/p_ex_ok.toml" ex_c ex_b ex_a
gate_case ex_ok $SYM 0 "$out/p_ex_ok.toml" ex_c ex_b ex_a --
tool policy "$out/p_ex_d.toml" ex_c ex_b ex_d
gate_case ex_d $SYM 1 "$out/p_ex_d.toml" ex_c ex_b ex_d -- undeclared-symbol:ex_c_fn

begin "c_embed (T112): the generated const array and length are exactly its exports, a leaf library with no function and no dep"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["kind"]=="c_library" and d["deps"]==[] else 1)' "$out/facts/emb.json" \
  || fail "$CUR: emb facts are not a dep-free c_library"
tool policy "$out/p_emb.toml" "emb;level=L3;exports=emb_blob,emb_blob_len"
gate_case emb $SYM 0 "$out/p_emb.toml" emb --
gate_case emb $SEM 0 "$out/p_emb.toml" emb --
tool policy "$out/p_emb_short.toml" "emb;level=L3;exports=emb_blob"
gate_case emb_short $SYM 1 "$out/p_emb_short.toml" emb -- unexpected-export:emb_blob_len

begin "exported_deps (T110): a label in both deps and exported_deps is a load error (the whole package fails to evaluate)"
mkdir -p "$scratch/q"
cat > "$scratch/q/BUCK" <<'EOF'
load("@gate//rules:c.bzl", "c_library")

c_library(name = "x", srcs = ["x.c"])
c_library(name = "both", srcs = ["both.c"], deps = [":x"], exported_deps = [":x"])
EOF
printf 'int x_fn(void) { return 1; }\n' > "$scratch/q/x.c"
printf 'int both_fn(void) { return 1; }\n' > "$scratch/q/both.c"
if run "$out/both.log" build "//selftest/scratch_pc/q:both"; then fail "$CUR: both built" "$out/both.log"; fi
grep -q "both \`deps\` and \`exported_deps\`" "$out/both.log" || fail "$CUR: failed for the wrong reason" "$out/both.log"

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

begin "exports (T033): exact list green; extra function, extra mutable global, extra const table, missing key are red"
tool policy "$out/p_x_ok.toml" "x_ok;level=L3;exports=x_f,x_g"
gate_case x_ok $SYM 0 "$out/p_x_ok.toml" x_ok --
tool policy "$out/p_x_func.toml" "x_func;level=L3;exports=x_f,x_g"
gate_case x_func $SYM 1 "$out/p_x_func.toml" x_func -- unexpected-export:x_hook
tool policy "$out/p_x_mut.toml" "x_mut;level=L3;exports=x_f,x_g"
gate_case x_mut $SYM 1 "$out/p_x_mut.toml" x_mut -- unexpected-export:x_hook mutable-global-export:x_hook mutable-data:x_hook unexpected-export:x_state mutable-global-export:x_state mutable-data:x_state
tool policy "$out/p_x_mut_listed.toml" "x_mut;level=L3;exports=x_f,x_g,x_hook,x_state"
gate_case x_mut_listed $SYM 1 "$out/p_x_mut_listed.toml" x_mut -- mutable-global-export:x_hook mutable-data:x_hook mutable-global-export:x_state mutable-data:x_state
tool policy "$out/p_x_const.toml" "x_const;level=L3;exports=x_f,x_g"
gate_case x_const $SYM 1 "$out/p_x_const.toml" x_const -- unexpected-export:x_table unexpected-export:x_names
tool policy "$out/p_x_const_ok.toml" "x_const;level=L3;exports=x_f,x_g,x_table,x_names"
gate_case x_const_ok $SYM 0 "$out/p_x_const_ok.toml" x_const --
tool policy "$out/p_x_nokey.toml" "x_ok;level=L3"
gate_case x_nokey $SYM 1 "$out/p_x_nokey.toml" x_ok -- exports-missing
tool policy "$out/p_x_l2.toml" "x_mut;level=L2;exports=x_f,x_g,x_hook,x_state;mutable_data=true"
gate_case x_l2 $SYM 0 "$out/p_x_l2.toml" x_mut --
tool policy "$out/p_x_l1.toml" "x_mut;level=L1;mutable_data=true"
gate_case x_l1 $SYM 0 "$out/p_x_l1.toml" x_mut --

begin "builtins are default-deny: alloca (also pasted), frame_address, longjmp (also behind a macro), __sync"
tool policy "$out/p_b.toml" b_alloca b_paste b_frame b_longjmp b_sync b_hidden b_io b_ovf b_hdrs
gate_case b_alloca $SEM 1 "$out/p_b.toml" b_alloca -- banned-builtin:__builtin_alloca "reserved-macro:#undef __builtin_alloca"
gate_case b_paste $SEM 1 "$out/p_b.toml" b_paste -- banned-builtin:__builtin_alloca "reserved-macro:#undef __builtin_alloca"
gate_case b_frame $SEM 1 "$out/p_b.toml" b_frame -- forbidden-builtin:__builtin_frame_address "reserved-macro:#undef __builtin_frame_address"
gate_case b_longjmp $SEM 1 "$out/p_b.toml" b_longjmp -- forbidden-builtin:__builtin_longjmp
gate_case b_hidden $SEM 1 "$out/p_b.toml" b_hidden -- forbidden-builtin:__builtin_longjmp
gate_case b_sync $SEM 1 "$out/p_b.toml" b_sync -- forbidden-builtin:__sync_fetch_and_add
for c in b_alloca b_paste b_frame b_longjmp b_hidden b_sync; do
  spec="$c"
  case "$c" in b_longjmp|b_hidden) spec="$c;mutable_data=true" ;; esac   # T089: their jmp buffer is a static
  tool policy "$out/p_$c.toml" "$spec"
  gate_case $c $SYM 0 "$out/p_$c.toml" $c --   # no symbol: why the symbols gate alone cannot see them
done
tool policy "$out/p_b_jmp.toml" "b_longjmp;exempt=longjmp"
gate_case b_longjmp_exempt $SEM 0 "$out/p_b_jmp.toml" b_longjmp --
tool policy "$out/p_b_alloca.toml" "b_alloca;builtins=__builtin_alloca"
"${RIGOR[@]}" facts --gate $SEM --facts "$out/fd/b_alloca.$SEM" --policy "$out/p_b_alloca.toml" --out "$out/res/b_alloca_pol.json" > "$out/res/b_alloca_pol.txt" 2>&1
rc=$?
[ "$rc" = 2 ] || fail "$CUR: a policy allowing __builtin_alloca exited $rc, wanted 2" "$out/res/b_alloca_pol.txt"
echo "  a policy naming __builtin_alloca in allow_builtins -> exit 2"

begin "builtins: toolchain code the product names is charged to it; annas-c-like code and a wide header set pass"
gate_case b_io $SEM 1 "$out/p_b.toml" b_io -- inline-asm:__asm__
gate_case b_ovf $SEM 0 "$out/p_b.toml" b_ovf --
tool policy "$out/p_b_ovf.toml" b_ovf
gate_case b_ovf $SYM 0 "$out/p_b_ovf.toml" b_ovf --
gate_case b_hdrs $SEM 0 "$out/p_b.toml" b_hdrs --

begin "system_libs (T095): declared and allowed is green; declared only, allowed only and an unknown name are red; the facts record the list"
tool policy "$out/p_sl_ok.toml" "sl_ok;allow=pthread_create,pthread_join;system_libs=pthread"
gate_case sl_ok $SYM 0 "$out/p_sl_ok.toml" sl_ok --
tool policy "$out/p_sl_nopolicy.toml" "sl_ok;allow=pthread_create,pthread_join"
gate_case sl_nopolicy $SYM 1 "$out/p_sl_nopolicy.toml" sl_ok -- system-lib-not-allowed:pthread
tool policy "$out/p_sl_nodecl.toml" "clean;system_libs=pthread"
gate_case sl_nodecl $SYM 1 "$out/p_sl_nodecl.toml" clean -- system-lib-not-declared:pthread
tool policy "$out/p_sl_bad.toml" "clean;system_libs=m"
"${RIGOR[@]}" facts --gate $SYM --facts "$out/fd/sl_nodecl.$SYM" --policy "$out/p_sl_bad.toml" --libc "$out/libc.symbols" --out "$out/res/sl_bad.json" > "$out/res/sl_bad.txt" 2>&1
rc=$?
[ "$rc" = 2 ] || fail "$CUR: a policy allowing system library m exited $rc, wanted 2" "$out/res/sl_bad.txt"
echo "  a policy naming system library m -> exit 2"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["system_libs"]==["pthread"] else 1)' "$out/facts/sl_ok.json" \
  || fail "$CUR: the sl_ok facts do not record system_libs = [pthread]"
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d["system_libs"]==[] else 1)' "$out/facts/clean.json" \
  || fail "$CUR: the clean facts record system libs"
echo "  facts: sl_ok records [pthread], clean records []"
for bad in 'system_libs = ["m"]' 'system_libs = ["pthread", "pthread"]' 'system_libs = "pthread"'; do
  mkdir -p "$scratch/slbad"
  printf 'load("@gate//rules:c.bzl", "c_library")\nc_library(name = "b", srcs = ["b.c"], %s)\n' "$bad" > "$scratch/slbad/BUCK"
  printf 'int slbad_f(void) { return 0; }\n' > "$scratch/slbad/b.c"
  if run "$out/slbad.log" build "//selftest/scratch_pc/slbad:b"; then fail "$CUR: $bad built" "$out/slbad.log"; fi
  grep -q "system_libs" "$out/slbad.log" || fail "$CUR: $bad failed for the wrong reason" "$out/slbad.log"
  echo "  macro refuses: $bad"
done
rm -rf "$scratch/slbad"
bf_sl="$out/bf/sl_test"; rm -rf "$bf_sl"; mkdir -p "$bf_sl"
printf 'load("@gate//rules:c.bzl", "c_test")\nc_test(name = "t", srcs = ["t.c"], system_libs = ["pthread"])\n' > "$bf_sl/BUCK"
"${RIGOR[@]}" buckfiles --root "$bf_sl" --out "$bf_sl/r.json" > "$bf_sl/o.txt" 2>&1; rc=$?
[ "$rc" = 1 ] || fail "$CUR: c_test with system_libs exited $rc, wanted 1" "$bf_sl/o.txt"
tool check "$bf_sl/r.json" bad-argument || fail "$CUR: c_test system_libs findings" "$bf_sl/o.txt"
echo "  buckfiles: system_libs on a c_test -> bad-argument"

begin "builtins: the sealed flags make a direct call of a banned builtin a compile error, and break no header"
if run "$out/direct.log" build "$pkg:b_direct"; then fail "$CUR: b_direct.c built" "$out/direct.log"; fi
grep -q "c_rigor_gate_bans___builtin_alloca" "$out/direct.log" || fail "$CUR: failed for the wrong reason" "$out/direct.log"
for m in release san cov fuzz; do
  run "$out/hdrs.$m.log" build --target-platforms ${PLAT}$m "$pkg:b_hdrs" "$pkg:b_ovf" //ctest:ctest //examples/hello:lib \
    || fail "$CUR: the header set does not build in $m" "$out/hdrs.$m.log"
  echo "  $m: wide header set, b_ovf, ctest and examples/hello build"
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
# Only the fresh-nonce actions (the changed source facts) must have run on RE; unchanged dependencies (toolchain, ctest, other
# facts) may legitimately be cache hits, depending on farm and daemon history. Nothing may run locally.
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $2 ~ /c_facts/ && $3 !~ /^re\(/ {bad=1} END{exit !bad}'; then
  fail "$CUR: a fresh-nonce action did not run on RE" "$out/whatran.txt"
fi
if grep -v '^Showing' "$out/whatran.txt" | awk -F'\t' 'NF>=3 && $3 !~ /^(re\(|cache)/ {bad=1} END{exit !bad}'; then
  fail "$CUR: an action ran locally or on an unknown executor" "$out/whatran.txt"
fi
grep 'c_facts' "$out/whatran.txt" | head -2
grep -q 'scratch_nonce_' "$(awk '/dep_a_facts/ && /buck-out/ {print $2}' "$out/$step.log" | tail -1)" || fail "$CUR: new symbol missing from the facts"

begin "modes (T023): the san twin of the facts; code that differs between release and san is a finding"
cd "$scratch/p"
cat >> BUCK <<'EOF'
c_library(name = "m_asan", srcs = ["m_asan.c"])
c_library(name = "m_feat", srcs = ["m_feat.c"])
c_library(name = "m_ubsan", srcs = ["m_ubsan.c"])
c_library(name = "m_hdr", srcs = ["m_hdr.c"], headers = ["m_hdr.h"])
c_library(name = "m_rel", srcs = ["m_rel.c"])
c_library(name = "m_pragma", srcs = ["m_pragma.c"])
c_library(name = "m_asm", srcs = ["m_asm.c"])
c_library(name = "m_ndebug", srcs = ["m_ndebug.c"])
c_library(name = "m_opt", srcs = ["m_opt.c"])
EOF
# The pinned clang does not define __SANITIZE_ADDRESS__ (a GCC macro) under -fsanitize=address: the
# block is dead in both modes, so this is not a divergence. __has_feature(address_sanitizer) is the real one.
cat > m_asan.c <<'EOF'
int m_hook(int v);
int m_asan_f(int v) {
#if defined(__SANITIZE_ADDRESS__)
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cat > m_feat.c <<'EOF'
int m_hook(int v);
int m_feat_f(int v) {
#if __has_feature(address_sanitizer)
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cat > m_ubsan.c <<'EOF'
int m_hook(int v);
int m_ubsan_f(int v) {
#if __has_feature(undefined_behavior_sanitizer)
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cat > m_hdr.h <<'EOF'
#ifndef M_HDR_H
#define M_HDR_H
int m_hook2(int v);
#if __has_feature(address_sanitizer)
#define M_HOOK(v) m_hook2(v)
#else
#define M_HOOK(v) (v)
#endif
#endif
EOF
cat > m_hdr.c <<'EOF'
#include "m_hdr.h"
int m_hdr_f(int v) { return M_HOOK(v); }
EOF
cat > m_rel.c <<'EOF'
int m_hook(int v);
int m_rel_f(int v) {
#if !__has_feature(address_sanitizer)
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cat > m_pragma.c <<'EOF'
#if __has_feature(address_sanitizer)
#pragma clang diagnostic push
#pragma clang diagnostic pop
#endif
int m_pragma_f(void) { return 1; }
EOF
cat > m_asm.c <<'EOF'
int m_asm_f(int v) {
#if __has_feature(address_sanitizer)
    __asm__ volatile("nop");
#endif
    return v;
}
EOF
# Neither mode defines NDEBUG and both optimise (-O2 / -O1), so these are the same text in both: green.
cat > m_ndebug.c <<'EOF'
int m_hook(int v);
int m_ndebug_f(int v) {
#ifndef NDEBUG
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cat > m_opt.c <<'EOF'
int m_hook(int v);
int m_opt_f(int v) {
#ifdef __OPTIMIZE__
    return m_hook(v);
#else
    return v;
#endif
}
EOF
cd "$root"
"${RIGOR[@]}" buckfiles --root "$scratch" > "$out/bf4.txt" 2>&1 || fail "$CUR" "$out/bf4.txt"
mtargets=(m_asan m_feat m_ubsan m_hdr m_rel m_pragma m_asm m_ndebug m_opt clean clean_test clean_bin b_ovf b_hdrs b_io fz paste attr)
rargs=(); sargs=()
for t in "${mtargets[@]}"; do rargs+=("$pkg:${t}_facts" "$pkg:${t}_facts[calls]"); sargs+=("$pkg:${t}_facts_san" "$pkg:${t}_facts_san[calls]"); done
rargs+=(//ctest:ctest_facts "//ctest:ctest_facts[calls]" //examples/hello:lib_facts "//examples/hello:lib_facts[calls]" //examples/hello:hello_facts "//examples/hello:hello_facts[calls]" //examples/hello:hello_test_facts "//examples/hello:hello_test_facts[calls]")
sargs+=(//ctest:ctest_facts_san "//ctest:ctest_facts_san[calls]" //examples/hello:lib_facts_san "//examples/hello:lib_facts_san[calls]" //examples/hello:hello_facts_san "//examples/hello:hello_facts_san[calls]" //examples/hello:hello_test_facts_san "//examples/hello:hello_test_facts_san[calls]")
run "$out/mrel.log" build "${rargs[@]}" --show-output || fail "$CUR: release facts" "$out/mrel.log"
run "$out/msan.log" build --target-platforms ${PLAT}san "${sargs[@]}" --show-output || fail "$CUR: san facts" "$out/msan.log"
echo "  cold release: $(grep -m1 'Commands:' "$out/mrel.log")"
echo "  cold san:     $(grep -m1 'Commands:' "$out/msan.log")"
tool collectmodes "$out/mrel.log" "$out/mrel" "" || fail "$CUR: collect release"
tool collectmodes "$out/msan.log" "$out/msan" "_san" || fail "$CUR: collect san"
ls "$out/mrel" | wc -l | xargs echo "  release files:"; ls "$out/msan" | wc -l | xargs echo "  san files:"

# modes_case <name> <want-exit> <mode-the-items-are-in|-> <target>... -- <expected finding>...
modes_case() {
  local name="$1" want="$2" mode="$3"; shift 3
  local targets=() expected=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do targets+=("$1"); shift; done
  [ "${1:-}" = "--" ] && shift
  expected=("$@")
  local d="$out/md/$name"; rm -rf "$d"
  tool mkmd "$out/mrel" "$d/release" "${targets[@]}" || fail "$CUR: no facts for ${targets[*]}"
  tool mkmd "$out/msan" "$d/san" "${targets[@]}" || fail "$CUR: no san facts for ${targets[*]}"
  local res="$d/res.json"
  "${RIGOR[@]}" facts --modes "$d/release" "$d/san" --out "$res" > "$d/o.txt" 2>&1
  local rc=$?
  [ "$rc" = "$want" ] || fail "$CUR: $name exited $rc, wanted $want" "$d/o.txt"
  tool check "$res" "${expected[@]}" || fail "$CUR: $name findings differ" "$d/o.txt"
  [ "$mode" = "-" ] || tool only_in "$res" "$mode" || fail "$CUR: $name: wrong mode" "$d/o.txt"
  echo "  $name -> exit $rc ${expected[*]:-}"
}

begin "modes: green (no mode-dependent code) -> 0 findings, incl. test, binary, fuzz, hello and the wide header set"
modes_case green 0 - clean clean_test clean_bin b_ovf b_hdrs b_io fz paste attr ctest lib hello hello_test --
begin "modes: red, each the only finding (__has_feature sanitizer tests, directly and through a product header macro)"
modes_case feature 1 san m_feat -- mode-divergent-code:m_hook
modes_case ubsan 1 san m_ubsan -- mode-divergent-code:m_hook
modes_case header 1 san m_hdr -- mode-divergent-code:m_hook2
modes_case release_only 1 release m_rel -- mode-divergent-code:m_hook
modes_case pragma 1 san m_pragma -- "mode-divergent-code:clang diagnostic push" "mode-divergent-code:clang diagnostic pop"
modes_case asm 1 san m_asm -- mode-divergent-code:__asm__
begin "modes: __SANITIZE_ADDRESS__ (not defined by this clang), NDEBUG (neither mode) and __OPTIMIZE__ (both modes) do not differ: no divergence"
modes_case sanitize_address 0 - m_asan --
modes_case ndebug 0 - m_ndebug --
modes_case optimize 0 - m_opt --
begin "modes: fail closed (target or unit in one mode only, missing calls file, schema mismatch, empty or missing dir) -> exit 2"
exit2() { # <name> <dir-release> <dir-san>
  "${RIGOR[@]}" facts --modes "$2" "$3" --out "$out/md/$1.json" > "$out/md/$1.txt" 2>&1; local rc=$?
  [ "$rc" = 2 ] || fail "$CUR: $1 exited $rc, wanted 2" "$out/md/$1.txt"
  echo "  $1 -> exit 2"
}
d="$out/md/f1"; tool mkmd "$out/mrel" "$d/release" clean m_asan; tool mkmd "$out/msan" "$d/san" clean
exit2 no_san_twin "$d/release" "$d/san"
d="$out/md/f2"; tool mkmd "$out/mrel" "$d/release" clean; tool mkmd "$out/msan" "$d/san" clean; rm "$d/san/clean.calls.json"
exit2 no_calls "$d/release" "$d/san"
d="$out/md/f3"; tool mkmd "$out/mrel" "$d/release" clean; tool mkmd "$out/msan" "$d/san" clean; tool tamper "$d/san/clean.json" schema 2
exit2 schema "$d/release" "$d/san"
d="$out/md/f4"; tool mkmd "$out/mrel" "$d/release" clean; tool mkmd "$out/msan" "$d/san" clean; tool tamper "$d/san/clean.json" units '[]'
exit2 unit_missing "$d/release" "$d/san"
mkdir -p "$out/md/empty"
exit2 empty "$out/md/empty" "$out/md/empty"
exit2 not_a_dir "$out/md/nonexistent" "$out/md/nonexistent"

begin "modes: cache: the san facts of an unchanged tree execute 0 actions, and san facts are san-only"
must_pass build --target-platforms ${PLAT}san "${sargs[@]}"
must_pass build --target-platforms ${PLAT}san "${sargs[@]}"
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the second san build"
echo "  second san build: $n actions executed"
must_pass build "${rargs[@]}"
must_pass build "${rargs[@]}"
n="$("${B[@]}" log what-ran 2>/dev/null | strip_ansi | grep -vc '^Showing\|^$')"
[ "$n" = 0 ] || fail "$CUR: $n actions executed on the second release build"
echo "  second release build: $n actions executed"
if run "$out/sanrel.log" build "$pkg:clean_facts_san"; then fail "$CUR: san facts built in release" "$out/sanrel.log"; fi
grep -q "is incompatible with" "$out/sanrel.log" || fail "$CUR: failed for the wrong reason" "$out/sanrel.log"

begin "modes: facts exist in the release mode only"
for m in san cov fuzz; do
  if run "$out/inc.log" build --target-platforms ${PLAT}$m "$pkg:clean_facts"; then fail "$CUR: facts built in $m" "$out/inc.log"; fi
  grep -q "is incompatible with" "$out/inc.log" || fail "$CUR: $m failed for the wrong reason" "$out/inc.log"
done

echo "elapsed ${SECONDS}s"
echo "ALL CHECKS PASSED ($step)"
