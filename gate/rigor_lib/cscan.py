"""Fact scanner. Runs inside a Buck2 action on RE (`rules/facts.bzl`), Python 3.8+ stdlib only.

    python3 -I -B cscan.py --label L --kind K [--dep D]... [--system-lib L]... --nm NM [--system-root R]... [--vendor-marker M]...
                           [--gate-marker M]...
                           [--unit NAME PREPROCESSED OBJECT]... --out FILE

It reports facts, never verdicts (the decision is `rigor facts`):
  * from each `clang -E` output (real compile flags, comments gone, macros expanded, line
    splices joined, tokens pasted): every `#pragma` line, every watched identifier (WATCHED_IDENTIFIERS
    and every identifier with a WATCHED_PREFIXES prefix: the compiler builtins), and every identifier
    inside `__attribute__((...))` / `[[...]]`;
  * every identifier fact says whether its file is the gate's own (`gate`: a file of buck-out under a cell other than
    the product's `root`, as the compiler read it; the same notion `mutate/gen.py` calls "a header of another cell");
  * the guards (T131): every call of `rigor_require` in product text (file, line, enclosing function), and, as
    identifier facts, every other use of that name in product text (a declaration, a definition, an address) and
    every product `#define`/`#undef` of it: the name is reserved (docs/require.md);
  * from each object: the defined, weak/indirect-defined and undefined external symbols (llvm-nm).
Text that comes from a system header (a file under a --system-root) is skipped: those are the
pinned toolchain's own headers, which are full of `__asm__` and attributes. A product reaches code in
them only by naming it, and can change them only through macros, so (T014):
  * a product use of a function (or initialised object) defined in toolchain text is charged with
    every watched identifier its body reaches, at the place of the use (`ToolchainCode`);
  * a product `#define`/`#undef` of a reserved identifier, a keyword or a macro the toolchain defines,
    and a toolchain header entered inside a product brace, are reported (as identifier facts named
    `#define X`, `#undef X`, `#include <h>`: the facts schema has no other place for them).
"""

import argparse
import json
import os
import re
import subprocess
import sys

SCHEMA = 1

# Identifiers reported wherever they occur outside strings and system headers.
WATCHED_IDENTIFIERS = (
    "asm", "__asm", "__asm__",
    "_Pragma", "__pragma",
    # alloca under every spelling (the builtin itself has the `__builtin_` prefix).
    "alloca", "__alloca", "_alloca",
    # Builtins of the pinned clang (19.1.7, -std=c17, x86-64) without a family prefix that are not C
    # library functions (calls to those keep their symbol, which the `symbols` gate judges). Found by
    # asking `__has_builtin` about every identifier in the clang binary (docs/product-checks.md).
    "__arithmetic_fence", "__rdtsc", "__xray_customevent", "__xray_typedevent",
    "_mm_clflush", "_mm_getcsr", "_mm_lfence", "_mm_mfence", "_mm_pause", "_mm_prefetch",
    "_mm_setcsr", "_mm_sfence",
)
# Every identifier with one of these prefixes is a compiler builtin: reported, and default-deny.
WATCHED_PREFIXES = (
    "__builtin_", "__sync_", "__atomic_", "__c11_atomic_", "__opencl_atomic_", "__hip_atomic_",
    "__scoped_atomic_",
)
# Names a product must not define or undefine besides reserved identifiers (C17 7.1.2p4, 7.1.3).
KEYWORDS = frozenset("""
    auto break case char const continue default do double else enum extern float for goto if inline
    int long register restrict return short signed sizeof static struct switch typedef union unsigned
    void volatile while
""".split())
ATTRIBUTE_INTRODUCERS = ("__attribute__", "__attribute")
# nm types of defined symbols that are weak, indirect (ifunc) or unique.
WEAK_DEFINED_TYPES = ("W", "V", "i", "I", "u")
UNDEFINED_TYPES = ("U", "w", "v")
# nm classes of defined external objects in writable storage: data, bss, small data, common (T033).
# Read-only data (`R`) and code (`T`) are not.
MUTABLE_TYPES = ("D", "B", "G", "S", "C")
# The objects are position independent, so a `const` table of addresses is in `.data.rel.ro` and nm says `D`.
# The linker makes that section read-only, so `read_relro` finds those names and they are not mutable.
RELRO_PREFIXES = (".data.rel.ro", ".tdata.rel.ro")

# Static data facts (T089): every defined object, local or external, with its size and section class.
# The class comes from the section name that `llvm-nm --format=sysv` prints, never from the nm letter
# (which cannot tell `.data.rel.ro` from `.data`, nor thread-local data from plain data).
DATA_TYPES = ("OBJECT", "TLS")
DATA_SECTIONS = (  # (prefix, class); the first match wins, so `.data.rel.ro` is tried before `.data`
    (".tdata.rel.ro", "ro"), (".tdata", "tls"), (".tbss", "tls"),
    (".data.rel.ro", "ro"), (".rodata", "ro"), (".lrodata", "ro"),
    (".data", "data"), (".sdata", "data"), (".ldata", "data"),
    (".bss", "bss"), (".sbss", "bss"), (".lbss", "bss"), ("*COM*", "bss"),
)

_MARKER = re.compile(r'^\s*#\s*(\d+)\s+"((?:[^"\\]|\\.)*)"((?:\s+\d+)*)\s*$')
# The compile command keeps macro definitions in the output (-dD); their bodies only matter when
# expanded, and the expansion is what the rest of the text shows.
_DEFINITION = re.compile(r"^\s*#\s*(define|undef)\b\s*([A-Za-z_][A-Za-z_0-9]*)?")
_PRAGMA = re.compile(r"^\s*#\s*pragma\b(.*)$")
_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<string>(?:u8|u|U|L)?"(?:[^"\\\n]|\\.)*")
  | (?P<char>(?:u8|u|U|L)?'(?:[^'\\\n]|\\.)*')
  | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<number>\.?[0-9](?:[eEpP][+-]|[A-Za-z0-9_.])*)
  | (?P<punct>%:%:|<%|%>|<:|:>|%:|.)
""", re.X | re.S)
_DIGRAPHS = {"<%": "{", "%>": "}", "<:": "[", ":>": "]", "%:": "#", "%:%:": "##"}
_VOLATILE_SEGMENT = re.compile(r"^[0-9a-f]{16}$")

# The guard primitive of `gate//rt:require` (T128/T131): a product may only call it.
GUARD_NAME = "rigor_require"
# What may stand before a call of it: the end of a statement, a block, a condition or a label; `else`/`do`.
CALL_PREVIOUS = frozenset((";", "{", "}", ")", ":", "else", "do"))
# Buck2 output layout `buck-out/<version>/{gen,art}/<cell>/...` and the cell of the product.
OUTPUT_KINDS = ("gen", "art")
PRODUCT_CELL = "root"


def display_file(path):
    """A path with Buck's configuration hashes removed, so findings do not depend on them."""
    if "/buck-headers/" in path:
        return path.split("/buck-headers/", 1)[1]
    return "/".join("~" if _VOLATILE_SEGMENT.match(part) else part for part in path.split("/"))


def output_tree(path):
    """(kind, cell, the components after the cell) of `buck-out/<version>/{gen,art}/<cell>/...`, or None when the path
    does not have that layout (the first `buck-out` is the real one; the output kind stands one or two components
    after it). The one path walk: every decision "is this the gate's file" starts here."""
    parts = os.path.normpath(path).split("/")
    if "buck-out" not in parts:
        return None
    rest = parts[parts.index("buck-out") + 1:]
    for index, part in enumerate(rest[:-2]):
        if part in OUTPUT_KINDS and 0 < index <= 2:
            return part, rest[index + 1], rest[index + 2:]
    return None


def vendor_tail(path, markers):
    """The part of `path` after the vendor marker (`mbedtls/ssl.h` for `/art/gate/third_party/`), or None. A file
    is gate third-party code only when its output tree starts, right after the version, with the marker. A
    fragment anywhere deeper (a product directory `x/art/gate/third_party/`) is the product's."""
    tree = output_tree(path)
    if tree is None:
        return None
    kind, cell, tail = tree
    start = "/" + "/".join((kind, cell) + tuple(tail)) + "/"
    for marker in markers:
        if start.startswith(marker):
            return start[len(marker):]
    return None


def is_gate_path(path, markers=()):
    """True when the compiler read `path` from the gate's output tree: a cell other than the product's, or (the gate being
    the root cell) a tree that starts, right after the output kind, with one of `markers` (`/<cell>/<package>/__<name>__/`).
    A marker is never matched anywhere else in the path, and an unrecognised layout is the product's."""
    tree = output_tree(path)
    if tree is None:
        return False
    _, cell, tail = tree
    if cell != PRODUCT_CELL:
        return True
    start = "/" + cell + "/" + "/".join(tail) + "/"
    return any(start.startswith(marker) for marker in markers)


def watched(name):
    return name in WATCHED_IDENTIFIERS or name.startswith(WATCHED_PREFIXES)


def reserved(name):
    """A name the product may not (re)define: reserved for the implementation, or a keyword."""
    return name.startswith("__") or (name[:1] == "_" and name[1:2].isupper()) or name in KEYWORDS


def tokens(line):
    """(kind, text) for every token of one preprocessed line, whitespace excluded; digraphs are
    returned in their primary spelling."""
    for match in _TOKEN.finditer(line):
        kind = match.lastgroup
        if kind != "space":
            text = match.group()
            yield kind, _DIGRAPHS.get(text, text) if kind == "punct" else text


class AttributeTracker:
    """Collects every identifier inside `__attribute__((...))` and `[[...]]`, across lines."""

    def __init__(self):
        self.mode = None      # None, "gnu" (after the keyword), "inside-gnu", "inside-bracket"
        self.depth = 0
        self.previous = None  # previous token text, for `[` `[` adjacency

    def feed(self, kind, text):
        """Returns True when this identifier token is inside an attribute list."""
        inside = False
        if self.mode is None:
            if kind == "ident" and text in ATTRIBUTE_INTRODUCERS:
                self.mode, self.depth = "gnu", 0
            elif text == "[" and self.previous == "[":
                self.mode, self.depth = "inside-bracket", 2
        elif self.mode == "gnu":
            if text == "(":
                self.depth += 1
                if self.depth == 2:
                    self.mode = "inside-gnu"
            else:
                self.mode = None      # not followed by `((`: nothing to collect
        else:
            inside = kind == "ident"
            opening, closing = ("(", ")") if self.mode == "inside-gnu" else ("[", "]")
            self.depth += (text == opening) - (text == closing)
            if self.depth <= 0:
                self.mode = None
        self.previous = text
        return inside


def _close(items, end):
    """Index of the `(` that matches the `)` at items[end]."""
    level = 0
    for index in range(end, -1, -1):
        level += (items[index] == ")") - (items[index] == "(")
        if level == 0:
            return index
    return None


_LABELS = ("__attribute__", "__attribute", "__asm__", "__asm", "asm")
_AGGREGATES = ("struct", "union", "enum")


def _top_equals(items):
    """Index of the first `=` outside every parenthesis (an initialiser), or None."""
    level = 0
    for index, text in enumerate(items):
        level += (text == "(") - (text == ")")
        if level == 0 and text == "=":
            return index
    return None


def owners(head):
    """What a `{` at file scope opens, from the declaration head before it: ("function", [name]),
    ("init", [names]) for an initialiser, ("aggregate", []) for a struct/union/enum body, or None
    when the shape is not one the toolchain headers use (the caller then stops trusting the text)."""
    equals = _top_equals(head)
    if equals is not None:
        return "init", declared_names(head[:equals])
    items = list(head)
    while items and items[-1] == ")":
        start = _close(items, len(items) - 1)
        if start is None:
            return None
        before = items[start - 1] if start > 0 else None
        if before in _LABELS:          # trailing __attribute__((...)) or asm("label")
            items = items[:start - 1]
            continue
        if before == "(" and start > 1 and items[start - 2] in _LABELS:
            items = items[:start - 2]
            continue
        if before is not None and _IDENT.fullmatch(before) and before not in KEYWORDS:
            return "function", [before]
        if before == ")":              # int (f)(void) / int (*f(void))(int)
            inner = items[_close(items, start - 1) or 0:start]
            names = [t for t in inner if _IDENT.fullmatch(t) and t not in KEYWORDS and t not in _LABELS]
            return ("function", names) if names else None
        return None
    if any(word in _AGGREGATES for word in head):
        return "aggregate", []
    return None


def declared_names(items):
    """Names a file-scope declarator list declares (fail-closed: every non-keyword identifier)."""
    return [t for t in items if _IDENT.fullmatch(t) and t not in KEYWORDS and t not in _LABELS]


_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class ToolchainCode:
    """Function bodies and initialisers in toolchain-header text, by name. A product that names one of
    them is charged with every watched identifier the code reaches (`reach`). The text is trusted
    only while it has the shapes the toolchain headers really use; on anything else (a `}` that
    closes nothing, a definition whose name cannot be read, a body left open when the product's text
    resumes) every watched identifier of toolchain text from there on is reported where it is."""

    def __init__(self):
        self.depth = 0
        self.head = []           # token texts of the file-scope declaration being read
        self.opened = None       # (kind, names) of the open body
        self.body = set()
        self.pending = []        # watched (name, file, line) seen in the open body and head
        self.bodies = {}         # name -> identifiers its body or initialiser names
        self.lost = False
        self.direct = set()      # (name, file, line) reported where they are

    def feed(self, kind, text, where):
        if kind == "ident" and watched(text):
            if self.lost:
                self.direct.add((text,) + where)
                return
            self.pending.append((text,) + where)
        if self.lost:
            return
        if self.depth == 0:
            self.file_scope(kind, text)
        else:
            self.in_body(kind, text)

    def file_scope(self, kind, text):
        if text == "{":
            self.opened = owners(self.head)
            if self.opened is None:
                self.lose()
                return
            self.depth, self.body = 1, set()
        elif text == "}":
            self.lose()
        elif text == ";":
            equals = _top_equals(self.head)
            if equals is not None:
                values = {t for t in self.head[equals:] if _IDENT.fullmatch(t)}
                for name in declared_names(self.head[:equals]):
                    self.bodies.setdefault(name, set()).update(values)
            if [t for t in self.head if t != "__extension__"][:1] in (["asm"], ["__asm"], ["__asm__"]):
                self.direct.update(self.pending)    # file-scope asm: code nobody has to call
            self.head, self.pending = [], []
        else:
            self.head.append(text)

    def in_body(self, kind, text):
        if kind == "ident":
            self.body.add(text)
        self.depth += (text == "{") - (text == "}")
        if self.depth:
            return
        kind_of, names = self.opened
        for name in names:
            self.bodies.setdefault(name, set()).update(self.body)
        if kind_of == "function":
            self.head, self.pending = [], []
        else:                    # the declaration goes on after a struct body or `= {...}`
            self.head.append("{}")

    def leave(self):
        """The product's text resumes: a body that is still open spans both."""
        if self.depth and not self.lost:
            self.lose()

    def lose(self):
        self.lost = True
        self.direct.update(self.pending)

    def reach(self):
        """name -> every watched identifier its code reaches, through other toolchain code."""
        found = {name: {i for i in body if watched(i)} for name, body in self.bodies.items()}
        calls = {name: {i for i in body if i in self.bodies and i != name}
                 for name, body in self.bodies.items()}
        changed = True
        while changed:
            changed = False
            for name, callees in calls.items():
                for callee in callees:
                    if not found[callee] <= found[name]:
                        found[name] |= found[callee]
                        changed = True
        return found


class GuardTracker:
    """The uses of `rigor_require` in product text, from the token stream of the preprocessed text. A use is a
    call (the name before `(`, after the end of a statement, block, condition or label: a call site with the
    function it is in) or anything else (a declaration, a definition, an address, a member: `misuse`)."""

    def __init__(self):
        self.depth = 0
        self.head = []           # token texts of the file-scope declaration being read
        self.opened = None       # what the open body is: "function" or other
        self.function = None     # name of the function whose body is open
        self.previous = None
        self.pending = None      # (file, line, previous, function) of a name waiting for its next token
        self.calls = set()       # (file, line, function)
        self.misuse = set()      # (file, line)

    def feed(self, kind, text, where):
        if self.pending is not None:
            file, line, before, function = self.pending
            self.pending = None
            if text == "(" and before in CALL_PREVIOUS:
                self.calls.add((file, line, function))
            else:
                self.misuse.add((file, line))
        if kind == "ident" and text == GUARD_NAME:
            self.pending = where + (self.previous, self.function or "<file scope>")
        self.track(text)
        self.previous = text

    def track(self, text):
        if self.depth == 0:
            if text == "{":
                owner = owners(self.head)
                self.opened = owner[0] if owner else None
                self.function = owner[1][0] if owner and owner[0] == "function" and owner[1] else "<unknown>"
                self.depth = 1
            elif text == ";":
                self.head = []
            elif text != "}":
                self.head.append(text)
            return
        self.depth += (text == "{") - (text == "}")
        if self.depth == 0:
            self.function = None
            self.head = [] if self.opened == "function" else self.head + ["{}"]

    def finish(self):
        if self.pending is not None:
            self.misuse.add(self.pending[:2])
            self.pending = None


class Collector:
    def __init__(self, system_roots, vendor_markers=(), gate_markers=()):
        self.roots = [os.path.normpath(root) + "/" for root in system_roots]
        # Gate-owned third-party header trees (`/art/<gate cell>/third_party/`, T108): text there is not the
        # product's either. A marker counts only right after `buck-out/<version>` (T133, `vendor_tail`).
        self.vendor = [marker for marker in vendor_markers if marker]
        # Path fragments of the gate's own header trees, for a gate that is the root cell (T131): `/<cell>/<pkg>/__<name>__/`.
        self.gate_markers = [marker for marker in gate_markers if marker]
        self.pragmas = set()
        self.attributes = set()
        self.identifiers = set()
        self.gate_identifiers = set()   # the same facts from the gate's own files (T131)
        self.guards = GuardTracker()
        self.line_directives = set()
        self.stack = []        # files we will return to (flag 1 pushes, flag 2 pops)
        self.current = None    # the file the compiler is really in; None before the first marker
        self.number = 0
        self.toolchain = ToolchainCode()
        self.uses = {}         # identifier -> {(file, line)} of every use in product text
        self.macros = []       # (directive, name, file, line) of every product #define/#undef
        self.toolchain_macros = set()
        self.depth = 0         # brace depth of the product's own text

    def is_system(self, path):
        if path.startswith("<"):   # "<built-in>" and "<command line>": the compiler's own text
            return True
        norm = os.path.normpath(path) + "/"
        return any(norm.startswith(root) for root in self.roots) \
            or vendor_tail(path, self.vendor) is not None

    def is_gate(self, path):
        """The compiler read `path` from the gate's own output tree: another cell than the product's, or a header tree
        the rule named (`--gate-marker`)."""
        return is_gate_path(path, self.gate_markers)

    def header_name(self, path):
        norm = os.path.normpath(path)
        for root in self.roots:
            if (norm + "/").startswith(root):
                return norm[len(root):]
        return display_file(path)

    def marker(self, match):
        """Follow one line marker. The compiler writes flag 1 (enter include) and flag 2 (return)
        itself; a marker with neither is either the compiler resynchronising line numbers (same
        file, moving forward, or the very first marker of the text) or a user `#line`, and
        a user `#line` is never believed: the file name stays what the compiler is really reading."""
        line = int(match.group(1))
        name = match.group(2).replace('\\"', '"').replace("\\\\", "\\")
        flags = match.group(3).split()
        if self.current is None:
            self.current, self.number = name, line - 1
        elif "1" in flags:
            self.entering(name)
            self.stack.append(self.current)
            self.current, self.number = name, line - 1
        elif "2" in flags:
            if self.stack and self.stack[-1] == name:
                self.stack.pop()
                self.current, self.number = name, line - 1
            else:
                self.line_directive(name)
        elif flags:   # only system-header flags: the compiler restating the current file
            self.number = line - 1
        elif name == self.current and line > self.number:
            self.number = line - 1
        else:
            self.line_directive(name)
            self.number = line - 1

    def entering(self, name):
        """A toolchain header entered inside a product brace (a function body, a struct) puts its
        text, and whatever product macros made of it, into the product's code."""
        if self.depth > 0 and not name.startswith("<") and self.is_system(name) \
                and not self.is_system(self.current):
            self.identifiers.add(("#include <%s>" % self.header_name(name),
                                  display_file(self.current), self.number))

    def line_directive(self, name):
        self.line_directives.add((name, display_file(self.current), self.number + 1))

    def scan(self, text):
        attributes = AttributeTracker()
        was_system = True
        for raw in text.split("\n"):
            self.number += 1
            marker = _MARKER.match(raw)
            if marker:
                self.marker(marker)
                continue
            current = self.current if self.current is not None else "<unknown>"
            system = self.is_system(current)
            if was_system and not system:
                self.toolchain.leave()
            was_system = system
            where = (display_file(current), self.number)
            gate = not system and self.is_gate(current)
            definition = _DEFINITION.match(raw)
            if definition:
                if system:
                    self.toolchain_macros.add(definition.group(2))
                else:
                    self.macros.append((definition.group(1), definition.group(2)) + where + (gate,))
                continue
            pragma = _PRAGMA.match(raw)
            if system:
                if not pragma:
                    for kind, tok in tokens(raw):
                        self.toolchain.feed(kind, tok, where)
                continue
            if pragma:
                self.pragmas.add(where + (pragma.group(1).strip(),))
                continue
            self.scan_line(raw, where, attributes, gate)
        self.toolchain.leave()
        self.guards.finish()

    def scan_line(self, raw, where, attributes, gate=False):
        for kind, tok in tokens(raw):
            if attributes.feed(kind, tok):
                self.attributes.add((tok,) + where)
            if kind == "ident":
                self.uses.setdefault(tok, set()).add(where)
                if watched(tok):
                    (self.gate_identifiers if gate else self.identifiers).add((tok,) + where)
            if not gate:
                self.guards.feed(kind, tok, where)
            self.depth += (tok == "{") - (tok == "}")

    def charged(self):
        """Watched identifiers the product reaches through toolchain code, at the places it names it."""
        found = set(self.toolchain.direct)
        for name, reached in self.toolchain.reach().items():
            for file, line in self.uses.get(name, ()):
                found.update((ident, file, line) for ident in reached)
        return found

    def macro_facts(self):
        """Product #define/#undef of a reserved name, a keyword or a macro the toolchain defines."""
        return {("#%s %s" % (directive, name or "?"), file, line)
                for directive, name, file, line, gate in self.macros
                if name is None or reserved(name) or name in self.toolchain_macros
                or (name == GUARD_NAME and not gate)}

    def result(self):
        misuse = {(GUARD_NAME, file, line) for file, line in self.guards.misuse}
        product = self.identifiers | self.charged() | self.macro_facts() | misuse
        found = [(a, f, n, False) for a, f, n in product]
        found += [(a, f, n, True) for a, f, n in self.gate_identifiers - product]
        return {
            "pragmas": [{"file": f, "line": n, "text": t} for f, n, t in sorted(self.pragmas)],
            "attributes": [{"name": a, "file": f, "line": n} for a, f, n in sorted(self.attributes)],
            "identifiers": [{"name": a, "file": f, "line": n, "gate": g} for a, f, n, g in sorted(found)],
            "guards": [{"file": f, "line": n, "function": fn} for f, n, fn in sorted(self.guards.calls)],
            "line_directives": [{"name": a, "file": f, "line": n} for a, f, n in sorted(self.line_directives)],
        }


def read_relro(nm, path):
    """Names of the defined symbols in a `.data.rel.ro*` section (`--format=sysv` names the section).

    This only ever removes names from `mutable`: output that does not parse gives the empty set, which
    reports more and never less."""
    done = subprocess.run([nm, "-g", "--defined-only", "--format=sysv", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise SystemExit("cscan: nm failed on %s: %s" % (path, done.stderr))
    relro = set()
    for line in done.stdout.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) == 7 and cells[6].startswith(RELRO_PREFIXES):
            relro.add(cells[0])
    return relro


def section_class(section, kind):
    """`ro`, `data`, `bss` or `tls` for a section a data symbol lives in; None for anything else
    (code, `.init_array`, `.eh_frame`, notes: not program data). A `TLS` symbol is always `tls`."""
    for prefix, name in DATA_SECTIONS:
        if section.startswith(prefix):
            return "tls" if kind == "TLS" else name
    return "tls" if kind == "TLS" else None


def read_data(nm, path):
    """Every defined data object of one object file, external and `static`: a list of
    {"name", "size", "section", "local"} sorted by name (`--format=sysv`, whose Size column is hex)."""
    done = subprocess.run([nm, "--defined-only", "--format=sysv", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise SystemExit("cscan: nm failed on %s: %s" % (path, done.stderr))
    found = []
    for line in done.stdout.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) != 7 or cells[3] not in DATA_TYPES:
            continue
        name, letter, kind, size, section = cells[0], cells[2], cells[3], cells[4], cells[6]
        klass = section_class(section, kind)
        if klass is None:
            continue
        try:
            number = int(size, 16)
        except ValueError:
            raise SystemExit("cscan: unreadable nm size %r in %s" % (size, path))
        found.append({"name": name, "size": number, "section": klass, "local": letter.islower()})
    return sorted(found, key=lambda item: (item["name"], item["section"], item["size"], item["local"]))


def read_symbols(nm, path):
    """(defined, weak_defined, undefined, mutable) external symbol names of one object file.

    `mutable` are the defined ones that live in writable storage (`MUTABLE_TYPES`)."""
    done = subprocess.run([nm, "-g", "--format=posix", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise SystemExit("cscan: nm failed on %s: %s" % (path, done.stderr))
    defined, weak, undefined, mutable = set(), set(), set(), set()
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            raise SystemExit("cscan: unreadable nm line %r in %s" % (line, path))
        name, kind = parts[0], parts[1]
        if kind in UNDEFINED_TYPES:
            undefined.add(name)
        else:
            defined.add(name)
            if kind in WEAK_DEFINED_TYPES:
                weak.add(name)
            if kind in MUTABLE_TYPES:
                mutable.add(name)
    return sorted(defined), sorted(weak), sorted(undefined), sorted(mutable - read_relro(nm, path))


def build_unit(args, name, preprocessed, obj):
    with open(preprocessed, "rb") as handle:
        text = handle.read().decode("utf-8", "replace")
    collector = Collector(args.system_root, args.vendor_marker, args.gate_marker)
    collector.scan(text)
    defined, weak, undefined, mutable = read_symbols(args.nm, obj)
    unit = {"name": name, "defined": defined, "weak": weak, "undefined": undefined, "mutable": mutable,
            "data": read_data(args.nm, obj)}
    unit.update(collector.result())
    return unit


def main(argv):
    parser = argparse.ArgumentParser(prog="cscan", allow_abbrev=False)
    parser.add_argument("--label", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--dep", action="append", default=[])
    parser.add_argument("--nm", required=True)
    parser.add_argument("--system-root", action="append", default=[])
    parser.add_argument("--vendor-marker", action="append", default=[])
    parser.add_argument("--gate-marker", action="append", default=[])
    parser.add_argument("--system-lib", action="append", default=[])
    parser.add_argument("--unit", nargs=3, action="append", default=[],
                        metavar=("NAME", "PREPROCESSED", "OBJECT"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    units = sorted((build_unit(args, *u) for u in args.unit), key=lambda u: u["name"])
    document = {"schema": SCHEMA, "label": args.label, "kind": args.kind,
                "deps": sorted(set(args.dep)), "system_libs": sorted(set(args.system_lib)), "units": units}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with open(args.out, "wb") as handle:
        handle.write(text.encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
