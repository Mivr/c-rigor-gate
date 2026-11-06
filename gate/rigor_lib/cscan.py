"""Fact scanner. Runs inside a Buck2 action on RE (`rules/facts.bzl`), Python 3.8+ stdlib only.

    python3 -I -B cscan.py --label L --kind K [--dep D]... --nm NM [--system-root R]...
                           [--unit NAME PREPROCESSED OBJECT]... --out FILE

It reports facts, never verdicts (the decision is `rigor facts`):
  * from each `clang -E` output (real compile flags, comments gone, macros expanded, line
    splices joined, tokens pasted): every `#pragma` line, every identifier from WATCHED_IDENTIFIERS,
    and every identifier inside `__attribute__((...))` / `[[...]]`;
  * from each object: the defined, weak/indirect-defined and undefined external symbols (llvm-nm).
Text that comes from a system header (a file under a --system-root) is skipped: those are the
pinned toolchain's own headers, which are full of `__asm__` and attributes.
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
    "__builtin_trap", "__builtin_unreachable", "__builtin_debugtrap",
)
ATTRIBUTE_INTRODUCERS = ("__attribute__", "__attribute")
# nm types of defined symbols that are weak, indirect (ifunc) or unique.
WEAK_DEFINED_TYPES = ("W", "V", "i", "I", "u")
UNDEFINED_TYPES = ("U", "w", "v")

_MARKER = re.compile(r'^\s*#\s*(\d+)\s+"((?:[^"\\]|\\.)*)"((?:\s+\d+)*)\s*$')
_PRAGMA = re.compile(r"^\s*#\s*pragma\b(.*)$")
_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<string>(?:u8|u|U|L)?"(?:[^"\\\n]|\\.)*")
  | (?P<char>(?:u8|u|U|L)?'(?:[^'\\\n]|\\.)*')
  | (?P<ident>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<number>\.?[0-9](?:[eEpP][+-]|[A-Za-z0-9_.])*)
  | (?P<punct>.)
""", re.X | re.S)
_VOLATILE_SEGMENT = re.compile(r"^[0-9a-f]{16}$")


def display_file(path):
    """A path with Buck's configuration hashes removed, so findings do not depend on them."""
    if "/buck-headers/" in path:
        return path.split("/buck-headers/", 1)[1]
    return "/".join("~" if _VOLATILE_SEGMENT.match(part) else part for part in path.split("/"))


def tokens(line):
    """(kind, text) for every token of one preprocessed line, whitespace excluded."""
    for match in _TOKEN.finditer(line):
        kind = match.lastgroup
        if kind != "space":
            yield kind, match.group()


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


class Collector:
    def __init__(self, system_roots):
        self.roots = [os.path.normpath(root) + "/" for root in system_roots]
        self.pragmas = set()
        self.attributes = set()
        self.identifiers = set()

    def is_system(self, path):
        if path.startswith("<"):   # "<built-in>" and "<command line>": the compiler's own text
            return True
        norm = os.path.normpath(path) + "/"
        return any(norm.startswith(root) for root in self.roots)

    def scan(self, text):
        current, number = "<unknown>", 0
        attributes = AttributeTracker()
        for raw in text.split("\n"):
            number += 1
            marker = _MARKER.match(raw)
            if marker:
                current = marker.group(2).replace('\\"', '"').replace("\\\\", "\\")
                number = int(marker.group(1)) - 1
                continue
            if self.is_system(current):
                continue
            where = (display_file(current), number)
            pragma = _PRAGMA.match(raw)
            if pragma:
                self.pragmas.add(where + (pragma.group(1).strip(),))
                continue
            self.scan_line(raw, where, attributes)

    def scan_line(self, raw, where, attributes):
        for kind, tok in tokens(raw):
            if attributes.feed(kind, tok):
                self.attributes.add((tok,) + where)
            if kind == "ident" and tok in WATCHED_IDENTIFIERS:
                self.identifiers.add((tok,) + where)

    def result(self):
        return {
            "pragmas": [{"file": f, "line": n, "text": t} for f, n, t in sorted(self.pragmas)],
            "attributes": [{"name": a, "file": f, "line": n} for a, f, n in sorted(self.attributes)],
            "identifiers": [{"name": a, "file": f, "line": n} for a, f, n in sorted(self.identifiers)],
        }


def read_symbols(nm, path):
    """(defined, weak_defined, undefined) external symbol names of one object file."""
    done = subprocess.run([nm, "-g", "--format=posix", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    if done.returncode != 0:
        raise SystemExit("cscan: nm failed on %s: %s" % (path, done.stderr))
    defined, weak, undefined = set(), set(), set()
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
    return sorted(defined), sorted(weak), sorted(undefined)


def build_unit(args, name, preprocessed, obj):
    with open(preprocessed, "rb") as handle:
        text = handle.read().decode("utf-8", "replace")
    collector = Collector(args.system_root)
    collector.scan(text)
    defined, weak, undefined = read_symbols(args.nm, obj)
    unit = {"name": name, "defined": defined, "weak": weak, "undefined": undefined}
    unit.update(collector.result())
    return unit


def main(argv):
    parser = argparse.ArgumentParser(prog="cscan", allow_abbrev=False)
    parser.add_argument("--label", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--dep", action="append", default=[])
    parser.add_argument("--nm", required=True)
    parser.add_argument("--system-root", action="append", default=[])
    parser.add_argument("--unit", nargs=3, action="append", default=[],
                        metavar=("NAME", "PREPROCESSED", "OBJECT"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    units = sorted((build_unit(args, *u) for u in args.unit), key=lambda u: u["name"])
    document = {"schema": SCHEMA, "label": args.label, "kind": args.kind,
                "deps": sorted(set(args.dep)), "units": units}
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with open(args.out, "wb") as handle:
        handle.write(text.encode("ascii") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
