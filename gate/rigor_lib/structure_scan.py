"""Structure fact scanner. Runs inside Buck2 actions on RE (`rules/structure.bzl`), Python 3.8+ stdlib only.

    structure_scan.py unit --label L --src SRC --out FILE [--system-root R]... [--vendor-marker M]... -- <clang command>
    structure_scan.py unit --label L --src SRC --out FILE [--system-root R]... --ast AST --include-list FILE
    structure_scan.py combine --label L --kind K [--dep D]... --src S... --out FILE UNIT.json...

`unit` runs the module's exact compile command (the argsfile Buck2 itself uses) with
`-Xclang -ast-dump=json -fsyntax-only -H` on one source and reduces clang's JSON AST to facts. It reports
numbers and edges, never verdicts (the decision is `rigor structure`). Any doubt (a location that does not
fit the file, a function the walk could not account for) exits non-zero and fails the build.

Locations. `#line` and `# N "file"` change the *presumed* file and line; the JSON dump also carries the
*actual* buffer name and byte offset. Only the latter are used: every line number is computed here from the
offset and the bytes of the real file, and cross-checked against the dump's own `line` attributes. A node
spelled inside a macro has two locations (where the text is written, where it expands): the body extent is the
larger of the two, and the function is flagged `macro`.

Per function (a definition outside the toolchain's own headers): where it is, the lines of its body (`{` line to
`}` line), parameters, deepest nesting of control statements and blocks, cyclomatic count, statement count, the
direct calls (callee key, expanded macros included, a `cleanup` attribute counts as a call), every call through
a value (`indirect`), and for a direct call whether a function or function-pointer value is passed along (`fp_args`).
Types (T063): each function carries its canonical function `type` and the `type` of each call through a value and
of each address taken; every place a function pointer may change type is a `conversion` (cast, union, copy,
va_arg) naming the function types involved, per function and per unit. See `Types` and docs/structure.md.
Per unit: every file the compiler read outside the toolchain (lines, bytes, longest line), and every reference to
a function that is not the callee of a call (`refs`: its address is taken).

Keys name a function: the link name (`mangledName`: an `__asm__("x")` label, or the aliasee of an `alias`
attribute) for external linkage; `static:FILE:NAME` for a static function (FILE where it is defined).
"""

import argparse
import bisect
import json
import os
import re
import subprocess
import sys
import threading

SCHEMA = 1
BODY_KINDS = {"IfStmt": 1, "WhileStmt": 1, "ForStmt": 4, "DoStmt": 0, "SwitchStmt": 1}
CONTROL = ("IfStmt", "WhileStmt", "ForStmt", "DoStmt", "SwitchStmt")
DECISIONS = ("IfStmt", "WhileStmt", "ForStmt", "DoStmt", "CaseStmt", "ConditionalOperator",
             "BinaryConditionalOperator", "GotoStmt", "IndirectGotoStmt")
PEEL_CAST = ("ImplicitCastExpr", "ParenExpr", "CStyleCastExpr")
_VOLATILE_SEGMENT = re.compile(r"^[0-9a-f]{16}$")
_INCLUDE_LINE = re.compile(r"^(\.+) (.+)$")


QUALIFIERS = frozenset(("const", "volatile", "restrict", "__restrict", "__restrict__", "_Atomic"))
INT_WORDS = frozenset(("unsigned", "signed", "short", "long", "int", "char"))
TYPE_WORDS = INT_WORDS | QUALIFIERS | frozenset(("void", "float", "double", "_Bool", "_Complex", "struct", "union",
                                                 "enum", "__int128", "__builtin_va_list"))
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\.\.\.|[0-9]+|\S")
_ATTRIBUTE = re.compile(r"__attribute__\s*\(\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)\)")
_UNNAMED = re.compile(r"\((?:unnamed|anonymous)[^()]*\)")
SAFE_CASTS = frozenset(("FunctionToPointerDecay", "LValueToRValue", "ArrayToPointerDecay", "NullToPointer",
                        "ToVoid", "BuiltinFnToFnPtr"))
COPIERS = frozenset(("memcpy", "memmove", "memcpy_s", "bcopy", "__builtin_memcpy", "__builtin_memmove",
                     "__memcpy_chk", "__memmove_chk", "__builtin___memcpy_chk", "__builtin___memmove_chk"))


def int_token(words):
    """One token for a run of integer keywords (`long unsigned int` and `unsigned long` are the same type)."""
    unsigned = "unsigned" in words
    if "char" in words:
        return "unsigned_char" if unsigned else ("signed_char" if "signed" in words else "char")
    longs = words.count("long")
    base = "short" if "short" in words else "long_long" if longs >= 2 else "long" if longs else "int"
    return ("unsigned_" if unsigned else "") + base


class Types:
    """Canonical function types from clang's type spellings.

    The dump prints a type with its typedefs resolved at the top only (`desugaredQualType`); a typedef inside a
    parameter list stays a name. So every typedef of the translation unit is expanded here (a name defined two
    ways is unknown), qualifiers are dropped (looser, so safe), integer spellings are unified, and `enum X` is
    the token `enum` (compatible with any integer type, C11 6.7.2.2p4). A canonical function type is its tokens
    joined by single spaces, `RET ( P , P )`: no parameter names, no pointer. Anything this cannot read is None:
    unknown, which the decision treats as matching everything."""

    def __init__(self, root):
        self.typedefs = {}
        self.records = {}
        stack = [root]
        while stack:
            node = stack.pop()
            kind = node.get("kind")
            if kind == "TypedefDecl" and node.get("name"):
                under = node.get("type", {}).get("qualType")
                known = self.typedefs.get(node["name"], under)
                self.typedefs[node["name"]] = under if known == under else None
            elif kind == "RecordDecl" and node.get("completeDefinition") and node.get("name"):
                key = "%s %s" % (node.get("tagUsed", "struct"), node["name"])
                self.records.setdefault(key, []).extend(self.members(node))
            stack.extend(children(node))
        self.busy = set()

    def members(self, record):
        """The members of a record: a type text each, or, for a member whose type is an unnamed struct or union
        (the declaration just before the field), the list of that record's members."""
        items, pending = [], []
        for child in children(record):
            if child.get("kind") == "RecordDecl" and not child.get("name") and child.get("completeDefinition"):
                pending.append(child)
            elif child.get("kind") == "FieldDecl":
                text = child.get("type", {}).get("qualType", "")
                if _UNNAMED.search(text) and "*" not in text and pending:
                    items.append(self.members(pending.pop(0)))
                else:
                    items.append(text)
        return items

    def item_types(self, item):
        """The function types of one member (see `members`); None = cannot tell."""
        if isinstance(item, str):
            return self.function_types(item, True)
        found = []
        for sub in item:
            part = self.item_types(sub)
            if part is None:
                return None
            found += part
        return sorted(set(found))

    def tokens(self, text):
        """The type's tokens with typedefs expanded, or None."""
        text = _UNNAMED.sub(" __anon__ ", _ATTRIBUTE.sub(" ", text))
        toks = [t for t in (TOKEN.findall(text) or []) if t not in QUALIFIERS]
        for _ in range(200):
            at = self.next_typedef(toks)
            if at is None:
                break
            toks = self.expand(toks, at)
            if toks is None:
                return None
        else:
            return None
        return self.unify(toks)

    def next_typedef(self, toks):
        for i, tok in enumerate(toks):
            if tok in TYPE_WORDS or not (tok[0].isalpha() or tok[0] == "_") or (i and toks[i - 1] in ("struct", "union", "enum")):
                continue
            if tok in self.typedefs:
                return i
        return None

    def expand(self, toks, i):
        under = self.typedefs[toks[i]]
        if under is None:
            return None
        under = [t for t in TOKEN.findall(_ATTRIBUTE.sub(" ", under)) if t not in QUALIFIERS]
        j = i + 1
        while j < len(toks) and toks[j] == "*":
            j += 1
        stars = ["*"] * (j - i - 1)
        if "[" in under:
            return None
        if "(" not in under:
            return toks[:i] + under + stars + toks[j:]
        k = under.index("(")
        if under[k + 1:k + 3] == ["*", ")"]:                  # a function pointer: the stars go inside
            return toks[:i] + under[:k + 2] + stars + under[k + 2:] + toks[j:]
        if stars and under[k + 1] != "*":                      # a function type: `fn_t *` is a pointer
            return toks[:i] + under[:k] + ["(", "*"] + stars[1:] + [")"] + under[k:] + toks[j:]
        return None

    def unify(self, toks):
        out, run, tag = [], [], False
        for tok in toks + [None]:
            if tok in INT_WORDS:
                run.append(tok)
                continue
            if run:
                out.append(int_token(run))
                run = []
            if tok is None:
                break
            if tag:                                   # the tag of `enum X` is dropped
                tag = False
                if out[-1] == "enum" and tok[0].isalpha():
                    continue
            tag = tok == "enum"
            out.append(tok)
        return out

    def function(self, text, pointer):
        """Canonical function type of a function (pointer=False) or of a pointer to one (pointer=True), or None."""
        toks = self.tokens(text)
        if toks is None or "(" not in toks or "[" in toks or "__anon__" in toks:
            return None
        k = toks.index("(")
        ret, rest = toks[:k], toks[k:]
        if pointer:
            if rest[:4] != ["(", "*", ")", "("]:
                return None
            rest = rest[3:]
        elif rest[1:2] == ["*"]:
            return None
        depth = 0
        for at, tok in enumerate(rest):
            depth += (tok == "(") - (tok == ")")
            if depth < 0 or (depth == 0 and at != len(rest) - 1):
                return None
        if not ret or depth != 0 or rest[-1] != ")":
            return None
        return " ".join(ret + rest)

    def function_types(self, text, deep):
        """The function types a value of type `text` holds: a function pointer (behind any pointer or array
        levels), and with `deep` a struct or union by value (its members, nested). None = cannot tell."""
        toks = self.tokens(text)
        if toks is None:
            return None
        if "(" in toks:
            k = toks.index("(")
            e = k + 1
            while e < len(toks) and (toks[e] in ("*", "[", "]") or toks[e].isdigit()):
                e += 1
            if e == k + 1 or e >= len(toks) or toks[e] != ")" or toks[k + 1] != "*":
                return None
            found = self.function(" ".join(toks[:k + 1] + ["*", ")"] + toks[e + 1:]), True)
            return None if found is None else [found]
        while toks and (toks[-1] in ("]", "[") or toks[-1].isdigit()):
            toks.pop()
        if not deep or "*" in toks or toks[:1] not in (["struct"], ["union"]):
            return []
        return self.record_types(" ".join(toks[:2]))

    def record_types(self, name):
        if name.endswith("__anon__"):
            return None
        if name in self.busy or name not in self.records:
            return []
        self.busy.add(name)
        found = []
        for field in self.records[name]:
            part = self.item_types(field)
            if part is None:
                found = None
                break
            found += part
        self.busy.discard(name)
        return None if found is None else sorted(set(found))


class ScanError(Exception):
    """The scan cannot be trusted; the action fails."""


def display_file(path):
    """A path with Buck's configuration hashes removed, so facts do not depend on them."""
    if "/buck-headers/" in path:
        return path.split("/buck-headers/", 1)[1]
    parts = os.path.normpath(path).split("/")
    return "/".join("~" if _VOLATILE_SEGMENT.match(part) else part for part in parts)


class SourceFile:
    """The bytes of one real file: line lookup from byte offsets."""

    def __init__(self, data):
        self.size = len(data)
        self.newlines = [i for i, byte in enumerate(data) if byte == 10]
        ends = [-1] + self.newlines + ([] if data.endswith(b"\n") or not data else [len(data)])
        self.lines = len(ends) - 1
        self.longest = max((b - a - 1 for a, b in zip(ends, ends[1:])), default=0)

    def line(self, offset):
        if not 0 <= offset <= self.size:
            raise ScanError("offset %d is outside a file of %d bytes" % (offset, self.size))
        return bisect.bisect_left(self.newlines, offset) + 1


class Files:
    """`system_roots` are the toolchain's own header directories; `vendor_markers` are path fragments of
    gate-owned third-party libraries (`/art/<gate cell>/third_party/`). Code in either is not the product's."""

    def __init__(self, system_roots, vendor_markers=()):
        self.roots = [os.path.normpath(root) + "/" for root in system_roots]
        self.vendor = list(vendor_markers)
        self.cache = {}

    def is_system(self, name):
        if name.startswith("<"):
            return True
        norm = os.path.normpath(name) + "/"
        return any(norm.startswith(root) for root in self.roots) or any(m in norm for m in self.vendor)

    def vendor_lib(self, name):
        """The directory name of the gate-owned third-party library a file belongs to (`mbedtls` for
        `.../art/<cell>/third_party/mbedtls/...`), or None."""
        norm = os.path.normpath(name) + "/"
        for marker in self.vendor:
            if marker in norm:
                lib = norm.split(marker, 1)[1].split("/")[0]
                return lib or None
        return None

    def get(self, name):
        """SourceFile of a real file, or None for `<scratch space>`, `<built-in>` and the like."""
        if name.startswith("<"):
            return None
        if name not in self.cache:
            try:
                with open(name, "rb") as handle:
                    self.cache[name] = SourceFile(handle.read())
            except OSError as exc:
                raise ScanError("cannot read %s: %s" % (name, exc)) from exc
        return self.cache[name]


class Place:
    """A resolved location: `spelling` and `expansion` are (file, line, offset) or None; plain code has both equal."""

    def __init__(self, spelling, expansion, macro):
        self.spelling = spelling
        self.expansion = expansion
        self.macro = macro


class Annotator:
    """Walks the dump in clang's print order (loc, range.begin, range.end, then inner), because a file
    name is only printed when it differs from the previous location printed."""

    def __init__(self, files):
        self.files = files
        self.current = ""
        self.main_seen = set()

    def bare(self, loc):
        if "file" in loc:
            self.current = loc["file"]
        self.main_seen.add(self.current)
        offset = loc.get("offset")
        if offset is None:
            return None
        source = self.files.get(self.current)
        line = source.line(offset) if source is not None else None
        if source is not None and "line" in loc and loc["line"] != line:
            raise ScanError("%s: the dump says line %s for offset %d, the file says %d"
                            % (self.current, loc["line"], offset, line))
        return (self.current, line, offset)

    def place(self, loc):
        if not isinstance(loc, dict) or not loc:
            return None
        if "spellingLoc" in loc or "expansionLoc" in loc:
            spelling = self.bare(loc["spellingLoc"]) if "spellingLoc" in loc else None
            expansion = self.bare(loc["expansionLoc"]) if "expansionLoc" in loc else None
            return Place(spelling, expansion or spelling, True)
        here = self.bare(loc)
        return Place(here, here, False) if here else None

    def visit(self, node):
        if not isinstance(node, dict) or not node:
            return
        if "loc" in node:
            node["_loc"] = self.place(node["loc"])
        if "range" in node:
            rng = node["range"]
            node["_begin"] = self.place(rng.get("begin"))
            node["_end"] = self.place(rng.get("end"))
        for child in node.get("inner", []):
            self.visit(child)


def children(node):
    return [c for c in node.get("inner", []) if isinstance(c, dict)]


def collect_decls(root):
    """Union-find over `previousDecl`, so every redeclaration of a function is one group."""
    parent = {}
    nodes = {}

    def find(i):
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    stack = [root]
    while stack:
        node = stack.pop()
        if node.get("kind") == "FunctionDecl" and "id" in node:
            find(node["id"])
            nodes.setdefault(node["id"], node)
            if node.get("previousDecl"):
                parent[find(node["id"])] = find(node["previousDecl"])
        stack.extend(children(node))
    groups = {}
    for ident, node in nodes.items():
        groups.setdefault(find(ident), []).append(node)
    return find, groups


def body_of(node):
    for child in children(node):
        if child.get("kind") == "CompoundStmt":
            return child
    return None


class Resolver:
    """decl id -> key of the function it names (see the module docstring)."""

    def __init__(self, root, files):
        self.files = files
        self.find, self.groups = collect_decls(root)
        self.keys = {}
        self.types = Types(root)

    def key_of(self, decl):
        """`decl` is a node or the `referencedDecl` stub of a DeclRefExpr."""
        ident = decl.get("id")
        group_id = self.find(ident) if ident is not None else None
        if group_id in self.keys:
            return self.keys[group_id]
        members = self.groups.get(group_id, [])
        key = self.compute(decl, members)
        if group_id is not None:
            self.keys[group_id] = key
        return key

    def compute(self, decl, members):
        name = decl.get("name", "")
        if not members:
            return name
        static = any(m.get("storageClass") == "static" for m in members)
        defined = [m for m in members if body_of(m) is not None]
        if static:
            if not defined:
                return "static:?:" + name
            return "static:%s:%s" % (self.definition_file(defined[0]), name)
        for member in members:
            for child in children(member):
                if child.get("kind") == "AliasAttr" and isinstance(child.get("aliasee"), str):
                    return child["aliasee"]
        for member in defined + members:
            if member.get("mangledName"):
                return member["mangledName"]
        return name

    def vendor_lib(self, decl):
        """The gate-owned third-party library that declares this function (T106), or None. A function the
        product declares itself is never taken for a library's."""
        ident = decl.get("id")
        for member in self.groups.get(self.find(ident) if ident is not None else None, []):
            place = member.get("_loc")
            lib = self.files.vendor_lib(place.expansion[0]) if place is not None and place.expansion else None
            if lib:
                return lib
        return None

    def definition_file(self, node):
        place = node.get("_loc")
        if place is None or place.expansion is None:
            raise ScanError("function %s has no location" % node.get("name"))
        return display_file(place.expansion[0])


def peel(expr):
    """Look through parentheses, casts, `*` and `&` for the named function a call really goes to."""
    while isinstance(expr, dict):
        kind = expr.get("kind")
        inner = children(expr)
        if kind in PEEL_CAST or (kind == "UnaryOperator" and expr.get("opcode") in ("*", "&")):
            if len(inner) != 1:
                return expr
            expr = inner[0]
        else:
            return expr
    return expr


def is_null_constant(node):
    """A null pointer constant (`0`, `(void *)0`, `NULL`): converting it to a function pointer type is fine."""
    while isinstance(node, dict):
        if node.get("castKind") == "NullToPointer" or (node.get("kind") == "IntegerLiteral" and node.get("value") == "0"):
            return True
        inner = children(node)
        if node.get("kind") not in ("ParenExpr", "ImplicitCastExpr", "CStyleCastExpr") or len(inner) != 1:
            return False
        node = inner[0]
    return False


def is_function_ref(node):
    ref = node.get("referencedDecl") if node.get("kind") == "DeclRefExpr" else None
    return ref if isinstance(ref, dict) and ref.get("kind") == "FunctionDecl" else None


def spelled(node):
    """The type text of a node (a declaration or an expression): the top-level desugared spelling when given."""
    typ = node.get("type", {})
    return typ.get("desugaredQualType") or typ.get("qualType", "")


def pointer_typed(node):
    typ = node.get("type", {})
    return "(*" in typ.get("qualType", "") or "(*" in typ.get("desugaredQualType", "")


class Measure:
    """Everything about one function body, from its AST."""

    def __init__(self, resolver, files):
        self.resolver = resolver
        self.files = files
        self.callee_nodes = set()
        self.conversions = {}

    def run(self, func):
        self.calls = {}
        self.indirect = []
        self.refs = []
        self.cyclomatic = 1
        self.statements = 0
        self.nesting = 0
        body = body_of(func)
        begin = body.get("_begin")
        self.home = begin.expansion[0] if begin is not None and begin.expansion else None
        self.foreign = False
        self.walk(body, 0, True, None, 0)
        return self

    def site(self, node):
        place = node.get("_begin")
        if place is None or place.expansion is None:
            if node.get("kind") != "CallExpr":
                return {"file": "unknown", "line": 0}
            raise ScanError("a call without a location")
        file, line, _ = place.expansion
        return {"file": display_file(file), "line": line}

    def call(self, node):
        inner = children(node)
        if not inner:
            raise ScanError("a call without a callee")
        callee = peel(inner[0])
        ref = is_function_ref(callee) if isinstance(callee, dict) else None
        args = inner[1:]
        if ref is None:
            site = self.site(node)
            site["type"] = self.resolver.types.function(spelled(inner[0]), True)
            self.indirect.append(site)
            return
        self.callee_nodes.add(id(callee))
        fp_args = any(is_function_ref(peel(a)) is not None or pointer_typed(a) for a in args)
        to = self.resolver.key_of(ref)
        entry = self.calls.setdefault((to, fp_args), {"to": to, "fp_args": fp_args,
                                                      "line": self.site(node)["line"]})
        entry["line"] = min(entry["line"], self.site(node)["line"])
        lib = self.resolver.vendor_lib(ref)
        if lib:
            self.vendor_call(entry, lib, args)

    def vendor_call(self, entry, lib, args):
        """A call into a gate-owned vendored library (T106): which functions it hands over (any function named
        inside an argument: directly, in an initialiser, in a compound literal), and whether an argument of
        function-pointer type is a value the scanner cannot name (a variable, a table element, a call result:
        then the decision keeps the conservative rule for this call)."""
        passes, opaque = set(), False
        for arg in args:
            self.named_functions(arg, passes)
            opaque = opaque or (pointer_typed(arg) and not is_null_constant(arg)
                                and is_function_ref(peel(arg)) is None)
        entry["lib"] = lib
        entry["passes"] = sorted(passes | set(entry.get("passes", [])))
        entry["opaque"] = opaque or entry.get("opaque", False)

    def named_functions(self, node, found):
        stack = [node]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            ref = is_function_ref(item)
            if ref is not None:
                found.add(self.resolver.key_of(ref))
            inner = children(item)
            if item.get("kind") == "CallExpr" and inner and is_function_ref(peel(inner[0])) is not None:
                inner = inner[1:]   # the callee of a nested call is called, not handed over
            stack.extend(inner)

    def note(self, node, kind, types):
        """A function pointer may change type here (or cannot be told): `types` are the function types involved,
        or None when unknown."""
        site = self.site(node)
        key = (site["file"], site["line"], kind, None if types is None else tuple(types))
        self.conversions[key] = {"file": site["file"], "line": site["line"], "kind": kind,
                                 "types": None if types is None else list(types)}

    def retyped(self, node, kind, src, dst):
        """Record a change from type text `src` to `dst` if a function type is involved and they differ."""
        types = self.resolver.types
        a, b = types.tokens(src), types.tokens(dst)
        if a is not None and a == b:
            return
        held = [types.function_types(src, False), types.function_types(dst, False)]
        if a is None or b is None or None in held:
            return self.note(node, kind, None)
        if held[0] or held[1]:
            self.note(node, kind, sorted(set(held[0] + held[1])))

    def convert(self, node):
        kind = node.get("kind")
        inner = children(node)
        if kind in ("ImplicitCastExpr", "CStyleCastExpr") and inner and node.get("castKind") not in SAFE_CASTS \
                and not is_null_constant(inner[0]):
            self.retyped(node, "cast", spelled(inner[0]), spelled(node))
        elif kind == "VAArgExpr":
            self.retyped(node, "vararg", "int", spelled(node))
        elif kind == "RecordDecl" and node.get("tagUsed") == "union" and node.get("completeDefinition"):
            self.union(node)
        elif kind == "CallExpr" and len(inner) >= 3:
            callee = peel(inner[0])
            ref = is_function_ref(callee) if isinstance(callee, dict) else None
            if ref is not None and ref.get("name") in COPIERS:
                self.copy(node, inner[1], inner[2])

    def union(self, node):
        """Reading a union member of another type reinterprets it: a union with a function pointer in it and a
        member of another type is a conversion."""
        types = self.resolver.types
        fields = types.members(node)
        held = [types.item_types(f) for f in fields]
        if None in held:
            return self.note(node, "union", None)
        flat = sorted({t for h in held for t in h})
        shapes = {tuple(types.tokens(f) or ("?",)) if isinstance(f, str) else ("aggregate", i)
                  for i, f in enumerate(fields)}
        if flat and len(shapes) > 1:
            self.note(node, "union", flat)

    def copy(self, node, dst, src):
        """memcpy and friends between objects of two types, one of which holds a function pointer, copy the
        pointer unseen."""
        types = self.resolver.types
        texts = []
        for arg in (dst, src):
            while isinstance(arg, dict) and arg.get("kind") in PEEL_CAST and len(children(arg)) == 1:
                arg = children(arg)[0]
            text = spelled(arg).strip()
            texts.append(text[:-1] if text.endswith("*") else re.sub(r"\s*\[[^\]]*\]$", "", text))
        self.retyped(node, "copy", texts[0], texts[1])

    def reference(self, node):
        ref = is_function_ref(node)
        if ref is None or id(node) in self.callee_nodes:
            return
        site = self.site(node)
        self.refs.append({"to": self.resolver.key_of(ref), "file": site["file"], "line": site["line"],
                          "type": self.resolver.types.function(spelled(ref), False)})

    def cleanup(self, node):
        target = node.get("cleanup_function")
        if isinstance(target, dict) and target.get("kind") == "FunctionDecl":
            line = node["_begin"].expansion[1] if node.get("_begin") and node["_begin"].expansion else 0
            self.calls.setdefault((self.resolver.key_of(target), False),
                                  {"to": self.resolver.key_of(target), "fp_args": False, "line": line})

    def bodies(self, node):
        """The statement children of a control statement that are its body, not its condition."""
        kind = node["kind"]
        inner = node.get("inner", [])
        if kind == "IfStmt":
            return [c for c in inner[1:] if isinstance(c, dict) and c]
        if kind == "DoStmt":
            return [c for c in inner[:1] if isinstance(c, dict) and c]
        if kind == "ForStmt":
            return [c for c in inner[4:] if isinstance(c, dict) and c]
        return [c for c in inner[1:] if isinstance(c, dict) and c]

    def walk(self, node, depth, transparent, parent, index):
        if not isinstance(node, dict) or not node:
            return
        kind = node.get("kind", "")
        inner = node.get("inner", [])
        place = node.get("_begin")
        self.convert(node)
        if place is not None and place.expansion and place.expansion[0] != self.home:
            self.foreign = True   # text of another file (an `#include` inside the body)
        if kind == "CompoundStmt":
            here = depth if transparent else depth + 1
            self.nesting = max(self.nesting, here)
            self.statements += sum(1 for c in inner if isinstance(c, dict) and c)
            for child in inner:
                self.walk(child, here, False, node, 0)
            return
        if kind in DECISIONS:
            self.cyclomatic += 1
        elif kind == "BinaryOperator" and node.get("opcode") in ("&&", "||"):
            self.cyclomatic += 1
        elif kind == "CallExpr":
            self.call(node)
        elif kind == "DeclRefExpr":
            self.reference(node)
        elif kind == "CleanupAttr":
            self.cleanup(node)
        here = depth
        if kind in CONTROL:
            else_if = (kind == "IfStmt" and parent is not None and parent.get("kind") == "IfStmt"
                       and parent.get("hasElse") and parent.get("inner", [None])[-1] is node)
            here = depth if else_if else depth + 1
            self.nesting = max(self.nesting, here)
            bodies = self.bodies(node)
            self.statements += sum(1 for b in bodies if b.get("kind") != "CompoundStmt")
            for child in inner:
                transparent_child = isinstance(child, dict) and child.get("kind") == "CompoundStmt"
                self.walk(child, here, transparent_child, node, 0)
            return
        if kind in ("LabelStmt", "CaseStmt", "DefaultStmt", "AttributedStmt"):
            subs = [c for c in inner if isinstance(c, dict) and c and not c.get("kind", "").endswith("Expr")
                    and c.get("kind") != "CompoundStmt"]
            self.statements += len(subs)
        for child in inner:
            self.walk(child, here, False, node, 0)


def extent(node, files):
    """(body_lines or None, macro) from the `{` and `}` of a body."""
    begin, end = node.get("_begin"), node.get("_end")
    if begin is None or end is None:
        raise ScanError("a function body without a plain or macro location")
    macro = begin.macro or end.macro
    sizes = []
    for part in ("spelling", "expansion"):
        a, b = getattr(begin, part), getattr(end, part)
        if a is None or b is None or a[1] is None or b[1] is None or a[0] != b[0]:
            continue
        if b[1] >= a[1]:
            sizes.append(b[1] - a[1] + 1)
    return (max(sizes) if sizes else None), macro


def scan_function(func, resolver, files):
    body = body_of(func)
    place = func.get("_loc")
    if place is None or place.expansion is None or place.expansion[1] is None:
        raise ScanError("function %s has no readable location" % func.get("name"))
    file, line, _ = place.expansion
    measured = Measure(resolver, files).run(func)
    lines, macro = extent(body, files)
    if measured.foreign:
        lines = None
    end = body.get("_end")
    end_line = (end.expansion or end.spelling)[1] if end is not None else None
    params = sum(1 for c in children(func) if c.get("kind") == "ParmVarDecl")
    if "..." in func.get("type", {}).get("qualType", ""):
        params += 1
    return {
        "name": func.get("name", ""),
        "key": resolver.key_of(func),
        "static": any(m.get("storageClass") == "static" for m in resolver.groups.get(resolver.find(func["id"]), [func])),
        "file": display_file(file),
        "line": line,
        "end_line": end_line,
        "body_lines": lines,
        "split": lines is None,
        "macro": macro,
        "params": params,
        "nesting": measured.nesting,
        "cyclomatic": measured.cyclomatic,
        "statements": measured.statements,
        "calls": sorted(measured.calls.values(), key=lambda c: (c["to"], c["fp_args"])),
        "indirect": measured.indirect,
        "refs": measured.refs,
        "type": resolver.types.function(spelled(func), False),
        "conversions": sorted(measured.conversions.values(), key=conv_order),
    }


def conv_order(entry):
    return (entry["file"], entry["line"], entry["kind"], json.dumps(entry["types"]))


def top_level_refs(nodes, resolver, files):
    """References to functions outside every function body (initialisers of tables and the like)."""
    measure = Measure(resolver, files)
    found = []
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if not isinstance(node, dict) or not node:
            continue
        if node.get("kind") == "CallExpr":
            inner = children(node)
            callee = peel(inner[0]) if inner else None
            if isinstance(callee, dict) and is_function_ref(callee):
                measure.callee_nodes.add(id(callee))
        if node.get("kind") == "DeclRefExpr":
            ref = is_function_ref(node)
            place = node.get("_begin")
            if ref is not None and id(node) not in measure.callee_nodes and place is not None:
                file, line, _ = place.expansion
                found.append({"to": resolver.key_of(ref), "file": display_file(file), "line": line,
                              "type": resolver.types.function(spelled(ref), False)})
        stack.extend(reversed(children(node)))
    return found


def top_level_conversions(nodes, resolver, files):
    """Function-pointer conversions outside every function body (initialisers, unions, casts in tables)."""
    measure = Measure(resolver, files)
    stack = list(nodes)
    while stack:
        node = stack.pop()
        if isinstance(node, dict) and node:
            measure.convert(node)
            stack.extend(children(node))
    return sorted(measure.conversions.values(), key=conv_order)


def analyse(ast, main_file, files):
    """-> (functions, top-level refs, top-level conversions, names of all files the dump located something in)."""
    annotator = Annotator(files)
    annotator.visit(ast)
    resolver = Resolver(ast, files)
    functions, rest, mine = [], [], []
    for top in children(ast):
        body = body_of(top) if top.get("kind") == "FunctionDecl" else None
        place = top.get("_loc")
        if top.get("isImplicit") or (place is not None and place.expansion
                                     and files.is_system(place.expansion[0])):
            if body is None:
                rest.append(top)
            continue
        if body is not None:
            functions.append(scan_function(top, resolver, files))
        else:
            rest.append(top)
            mine.append(top)
    # every definition the tree holds must have been accounted for (a nested or odd one is a scan failure)
    placed = sum(1 for m in (n for g in resolver.groups.values() for n in g)
                 if body_of(m) is not None and not m.get("isImplicit")
                 and not (m.get("_loc") and m["_loc"].expansion and files.is_system(m["_loc"].expansion[0])))
    if placed != len(functions):
        raise ScanError("the tree holds %d function definitions, the scan accounted for %d"
                        % (placed, len(functions)))
    refs = top_level_refs(rest, resolver, files)
    return functions, refs, top_level_conversions(mine, resolver, files), annotator.main_seen


def file_facts(names, files):
    facts = {}
    for name in names:
        source = files.get(name)
        if source is None or files.is_system(name):
            continue
        facts[display_file(name)] = {"path": display_file(name), "lines": source.lines,
                                     "bytes": source.size, "longest_line": source.longest}
    return [facts[k] for k in sorted(facts)]


def parse_include_list(text, files):
    names = []
    for line in text.splitlines():
        match = _INCLUDE_LINE.match(line)
        if match and not files.is_system(match.group(2)):
            names.append(os.path.normpath(match.group(2)))
    return names


_WRAPPER_LINE = re.compile(r'#[ \t]*include[ \t]*"([^"\n]+)"')


def strip_comments(text):
    """The text with comments removed (a comment becomes one space, as in translation phase 3)."""
    text = text.replace("\\\n", "")
    out, i, size = [], 0, len(text)
    while i < size:
        two = text[i:i + 2]
        if two == "//":
            end = text.find("\n", i)
            i = size if end < 0 else end
            out.append(" ")
        elif two == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise ScanError("unterminated comment")
            i = end + 2
            out.append(" ")
        elif text[i] == '"':
            end = text.find('"', i + 1)
            end = size - 1 if end < 0 else end
            out.append(text[i:end + 1])
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def check_wrapper(src, include_text, seen, files):
    """A main file the dump never names is accepted only as a wrapper: nothing but `#include "x"` lines, and the
    dump has a location in every file they name. Anything else would be a scan that saw nothing of the source."""
    blind = "no location of the dump names %s; the scan would be blind" % src
    with open(src, "rb") as handle:
        text = handle.read().decode("utf-8", "replace")
    try:
        lines = [ln.strip() for ln in strip_comments(text).splitlines() if ln.strip()]
    except ScanError as exc:
        raise ScanError("%s (%s)" % (blind, exc)) from exc
    wanted = []
    for line in lines:
        match = _WRAPPER_LINE.fullmatch(line)
        if match is None:
            raise ScanError("%s (it is not only `#include \"...\"` lines)" % blind)
        wanted.append(os.path.normpath(match.group(1)))
    if not wanted:
        raise ScanError("%s (it is empty)" % blind)
    located = {os.path.normpath(n) for n in seen}
    read = parse_include_list(include_text, files)
    for name in wanted:
        hits = [r for r in read if r == name or r.endswith("/" + name)]
        if not any(h in located for h in hits):
            raise ScanError("%s (the included %s produced no location)" % (blind, name))


def unit_facts(label, src, ast, include_text, files):
    main = os.path.normpath(src)
    functions, refs, conversions, seen = analyse(ast, main, files)
    if not any(os.path.normpath(n) == main for n in seen):
        check_wrapper(src, include_text, seen, files)
    names = {main}
    names.update(parse_include_list(include_text, files))
    names.update(os.path.normpath(n) for n in seen if not n.startswith("<") and not files.is_system(n))
    return {"src": display_file(src), "files": file_facts(sorted(names), files),
            "functions": sorted(functions, key=lambda f: (f["file"], f["line"], f["key"])),
            "refs": sorted(refs, key=lambda r: (r["file"], r["line"], r["to"])),
            "conversions": conversions}


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def cmd_unit(args, command):
    files = Files(args.system_root, args.vendor_marker)
    if command:
        done = subprocess.run(command + ["-Xclang", "-ast-dump=json", "-fsyntax-only", "-H", args.src],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            sys.stderr.write(done.stderr.decode("utf-8", "replace"))
            raise ScanError("clang failed with status %d" % done.returncode)
        ast = json.loads(done.stdout)
        include_text = done.stderr.decode("utf-8", "replace")
    else:
        with open(args.ast, "rb") as handle:
            ast = json.loads(handle.read())
        with open(args.include_list, "r", encoding="utf-8") as handle:
            include_text = handle.read()
    unit = unit_facts(args.label, args.src, ast, include_text, files)
    with open(args.out, "wb") as handle:
        handle.write(canonical(unit))


def cmd_combine(args):
    units = []
    for path in args.units:
        with open(path, "rb") as handle:
            units.append(json.loads(handle.read()))
    wanted = sorted(display_file(s) for s in args.src)
    got = sorted(u["src"] for u in units)
    if got != wanted:
        raise ScanError("units %r do not match the sources %r" % (got, wanted))
    document = {"schema": SCHEMA, "label": args.label, "kind": args.kind, "deps": sorted(args.dep),
                "srcs": wanted, "units": sorted(units, key=lambda u: u["src"])}
    with open(args.out, "wb") as handle:
        handle.write(canonical(document))


def main(argv):
    command = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="mode", required=True)
    unit = sub.add_parser("unit")
    unit.add_argument("--label", required=True)
    unit.add_argument("--src", required=True)
    unit.add_argument("--out", required=True)
    unit.add_argument("--system-root", action="append", default=[])
    unit.add_argument("--vendor-marker", action="append", default=[])
    unit.add_argument("--ast")
    unit.add_argument("--include-list")
    comb = sub.add_parser("combine")
    comb.add_argument("--label", required=True)
    comb.add_argument("--kind", required=True)
    comb.add_argument("--dep", action="append", default=[])
    comb.add_argument("--src", action="append", default=[])
    comb.add_argument("--out", required=True)
    comb.add_argument("units", nargs="+")
    args = parser.parse_args(argv)
    try:
        if args.mode == "unit":
            if bool(command) == bool(args.ast):
                raise ScanError("give either a clang command after -- or --ast with --include-list")
            cmd_unit(args, command)
        else:
            cmd_combine(args)
    except (ScanError, ValueError, KeyError, OSError) as exc:
        sys.stderr.write("structure_scan: %s: %s\n" % (type(exc).__name__, exc))
        return 1
    return 0


def run_big_stack(argv):
    """The dump nests as deep as the code does; walk it on a thread with room for that."""
    sys.setrecursionlimit(200000)
    threading.stack_size(1024 * 1024 * 1024)
    result = []
    thread = threading.Thread(target=lambda: result.append(main(argv)))
    thread.start()
    thread.join()
    return result[0] if result else 1


if __name__ == "__main__":
    sys.exit(run_big_stack(sys.argv[1:]))
