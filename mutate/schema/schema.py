#!/usr/bin/env python3
"""Schema generator of the schema mutation engine (T124; design in docs/mutate-schema.md). Python 3 stdlib only.

    schema.py generate --src SRC --gen-json GEN --live IDS --first-index N --gen-py GEN.PY --rt-include DIR
                       --out-src F --out-obj F --out-table F [--system-root R]... -- <module compile prefix>

One schema source for one source file: every mutant of GEN (the list mutate/gen.py wrote: same mutants, same ids)
that is in IDS (the ids v1 would run) and is schema-eligible is compiled in, switchable at run time by
`rigor_hit(N)` (mutate/schema/schema_rt.h). The wrapper depends on where the mutant sits:

    expression   (rigor_hit(N) ? (mutated) : (original))
    condition    ((cond) ? !rigor_hit(N) : rigor_hit(N))        the controlling expression of if/while/do/for
    statement    if (!rigor_hit(N)) { call(); }                 a deleted call statement
    function     if (rigor_hit(N)) { <v1's replacement body> }  inserted after the opening brace

Eligibility is decided from the clang AST (the one the module's exact command prints), never from text: the AST
parent says whether a site is a constant-expression context, a string literal initialising an array, and so on.
Mutants whose expression ranges nest are wrapped inside the outer one's `original` arm; ranges that overlap only
partly are not eligible. A schema that does not compile is searched for the offending mutants by bisection.

The table (`--out-table`) says, for every mutant of IDS, what became of it: an entry with its index, a reason code
for "not eligible", or `schema-unviable`.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

SCHEMA_TABLE = 1
MAX_INDEX = 131071  # RIGOR_SCHEMA_MAX - 1 (schema_rt.h)

CONSTANT_CONTEXT = "constant-context"
ARRAY_STRING_INIT = "array-string-init"
TYPE_CHANGE = "type-change"
PARTIAL_OVERLAP = "partial-overlap"
NO_ANCHOR = "no-anchor"
DIRECTIVE = "directive-in-range"
SCHEMA_UNVIABLE = "schema-unviable"
REASONS = (CONSTANT_CONTEXT, ARRAY_STRING_INIT, TYPE_CHANGE, PARTIAL_OVERLAP, NO_ANCHOR, DIRECTIVE, SCHEMA_UNVIABLE)

CONSTANT_KINDS = ("ConstantExpr", "StaticAssertDecl", "EnumConstantDecl", "FieldDecl", "DesignatedInitExpr",
                  "UnaryExprOrTypeTraitExpr")
TRANSPARENT = ("ParenExpr", "ImplicitCastExpr")
INT_PROMOTED = frozenset(("int", "short", "short int", "signed short", "char", "signed char", "unsigned char",
                          "unsigned short", "unsigned short int", "_Bool", "bool", "signed int"))
BINARY_OPS = ("relational", "arithmetic", "logical", "compound-assignment")
NO_RANGE_KINDS = ("insert",)
DIRECTIVE_AT = re.compile(rb"\n[ \t]*#")
LITERAL = re.compile(r"(0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)([uUlL]*)")
PROLOGUE = '#include "schema_rt.h"\n#line 1\n'


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def literal_type(text):
    """The C type name of an integer literal's text on LP64 (C17 6.4.4.1), or None when no type holds its value."""
    found = LITERAL.fullmatch(text)
    if not found:
        return None
    digits, suffix = found.group(1), found.group(2).lower()
    hexa = digits[:2] in ("0x", "0X")
    value = int(digits, 16 if hexa else 10)
    unsigned = "u" in suffix
    first = min(suffix.count("l"), 2)  # the lowest rank (int, long, long long) the suffix allows
    names = ("int", "long", "long long")
    signed_bits, unsigned_bits = (31, 63, 63), (32, 64, 64)
    order = []
    for rank in range(first, 3):
        if not unsigned:
            order.append((names[rank], signed_bits[rank]))
        if unsigned or hexa:
            order.append(("unsigned " + names[rank], unsigned_bits[rank]))
    for name, bits in order:
        if value < (1 << bits):
            return name
    return None


class Anchor:
    """One schema-eligible-so-far mutant: where it sits (`begin`, `end` of the range that carries the wrapper), the
    wrapper `kind` and the text the wrapper needs."""

    def __init__(self, mutant, order, kind, begin, end, node, **extra):
        self.mutant, self.order, self.kind, self.begin, self.end, self.node = mutant, order, kind, begin, end, node
        self.extra = extra
        self.index = 0

    def key(self):
        return (self.begin, 0 if self.begin == self.end else 1, -self.end, self.order)


class AstIndex:
    """The AST of one source, with parents, and the lookups that tie a mutant of `gen.py` to its node."""

    def __init__(self, gen, ast, file, data, roots=()):
        self.gen, self.data, self.file = gen, data, file
        gen.annotate(ast, file, data)
        self.source = gen.Source(data)
        self.walker = gen.Walker(self.source, file, roots)
        self.operators = {}   # (begin, end) of an operator token -> node
        self.spans = {}       # (kind, begin, end) -> node
        self.conditions = {}  # span of a controlling expression -> its node
        self.returns = {}     # span of a returned expression -> its node
        self.calls = {}       # span of a call that is a statement -> node
        self.strings = []     # (begin, end, node) of string literals
        self._walk(ast)

    def _walk(self, ast):
        ast["_parent"] = None
        stack = [ast]
        while stack:
            node = stack.pop()
            for child in node.get("inner", []):
                if isinstance(child, dict):
                    child["_parent"] = node
                    stack.append(child)
            self._enter(node)

    def _enter(self, node):
        kind = node.get("kind", "")
        span = self.gen.span_of(node)
        if span is not None:
            self.spans.setdefault((kind, span[0], span[1]), node)
        if kind in ("BinaryOperator", "CompoundAssignOperator"):
            self._binary(node)
        elif kind == "UnaryOperator" and span is not None:
            self._unary(node, span)
        elif kind in self.gen.CONDITION_SLOT:
            cond = self.walker.condition_of(kind, node.get("inner", []))
            shown = self.walker.value_span(cond)
            if shown is not None:
                self.conditions.setdefault(shown, node)
        elif kind == "ReturnStmt" and len(node.get("inner", [])) == 1:
            shown = self.walker.value_span(node["inner"][0])
            if shown is not None:
                self.returns.setdefault(shown, node)
        elif kind == "CallExpr" and span is not None and (node.get("_parent") or {}).get("kind") == "CompoundStmt":
            self.calls.setdefault(span, node)
        elif kind == "StringLiteral" and span is not None:
            self.strings.append((span[0], span[1], node))

    def _binary(self, node):
        children = node.get("inner", [])
        opcode = node.get("opcode")
        if len(children) != 2 or not opcode:
            return
        lhs, rhs = self.gen.operand_span(children[0]), self.gen.operand_span(children[1])
        if lhs is None or rhs is None:
            return
        at = self.source.token_between(lhs[1], rhs[0], opcode.encode("ascii"))
        if at is not None:
            node["_operands"] = (lhs[0], rhs[1])
            self.operators[(at, at + len(opcode))] = node

    def _unary(self, node, span):
        opcode = node.get("opcode")
        if opcode == "!":
            at = span[0]
        elif opcode in ("++", "--"):
            at = span[1] - 2 if node.get("isPostfix") else span[0]
        else:
            return
        self.operators[(at, at + len(opcode))] = node

    def ancestors(self, node):
        node = node.get("_parent")
        while node is not None:
            yield node
            node = node.get("_parent")

    def outer_of(self, node):
        """(parent, child) seen through parentheses and implicit conversions: the first ancestor that is neither."""
        child, parent = node, node.get("_parent")
        while parent is not None and parent.get("kind") in TRANSPARENT:
            child, parent = parent, parent.get("_parent")
        return parent, child


def operand_type(node):
    typ = (node.get("inner") or [{}])[0].get("type", {})
    return typ.get("desugaredQualType") or typ.get("qualType", "")


def truthy_context(index, node):
    """Is the value of this expression only ever tested for being zero (a condition, `&&`, `||`, `!`, `?:`)?"""
    parent, child = index.outer_of(node)
    kind = (parent or {}).get("kind")
    if kind in index.gen.CONDITION_SLOT:
        slot = index.gen.CONDITION_SLOT[kind]
        inner = parent.get("inner", [])
        return len(inner) > slot and inner[slot] is child
    if kind == "BinaryOperator":
        return parent.get("opcode") in ("&&", "||")
    if kind == "UnaryOperator":
        return parent.get("opcode") == "!"
    if kind == "ConditionalOperator":
        return parent.get("inner", [None])[0] is child
    return False


def constant_context(index, node):
    """Is the node inside something the language wants as a constant expression (AST parents, up to the function)?"""
    for anc in index.ancestors(node):
        kind = anc.get("kind", "")
        if kind == "FunctionDecl":
            return False
        if kind in CONSTANT_KINDS:
            return True
        if kind == "VarDecl" and (anc.get("storageClass") in ("static", "extern") or anc.get("tls")):
            return True
    return False


def array_string_init(index, node):
    parent = node.get("_parent") or {}
    return parent.get("kind") in ("VarDecl", "InitListExpr")


def types_differ(mutant):
    """Does the replacement give a literal another type than the original (so the conditional's type would change)?"""
    if mutant["operator"] == "integer-literal":
        return literal_type(mutant["original"]) != literal_type(mutant["replacement"])
    if mutant["operator"] == "char-literal":
        return re.match(r"(u8|u|U)'", mutant["original"]) is not None
    return False


class Planner:
    """Turns the mutants of one source into anchors and reasons."""

    def __init__(self, index):
        self.index = index
        self.data = index.data

    def plan(self, mutants):
        """(anchors, {id: reason}) for the mutants, in their order."""
        anchors, rejected = [], {}
        for order, mutant in enumerate(mutants):
            found = self.anchor(mutant, order)
            if isinstance(found, str):
                rejected[mutant["id"]] = found
            else:
                anchors.append(found)
        for anchor in self.overlapping(anchors):
            rejected[anchor.mutant["id"]] = PARTIAL_OVERLAP
        return [a for a in anchors if a.mutant["id"] not in rejected], rejected

    def anchor(self, mutant, order):
        node, kind, rng = self.locate(mutant)
        if node is None:
            return NO_ANCHOR
        if kind != "insert" and DIRECTIVE_AT.search(self.data[rng[0]:rng[1]]):
            return DIRECTIVE
        if kind != "insert" and kind != "stmt" and constant_context(self.index, node):
            return CONSTANT_CONTEXT
        extra = {}
        if mutant["operator"] == "string-literal" and array_string_init(self.index, node):
            return ARRAY_STRING_INIT
        if types_differ(mutant):
            return TYPE_CHANGE
        if mutant["operator"] == "not-removal":
            extra = self.not_removal(node, rng)
            if extra is None:
                return TYPE_CHANGE
        if kind == "expr" and "arm" not in extra:
            begin, end = mutant["begin_offset"], mutant["end_offset"]
            extra["arm"] = self.data[rng[0]:begin] + mutant["replacement"].encode("latin-1") + self.data[end:rng[1]]
        return Anchor(mutant, order, kind, rng[0], rng[1], node, **extra)

    def not_removal(self, node, rng):
        """`!x` -> `x`. Exact only if the value stays an int; if the value is only tested for zero, `!!x` says the same."""
        if truthy_context(self.index, node):
            return {"arm": b"!!(" + self.data[rng[0] + 1:rng[1]] + b")"}
        if operand_type(node) in INT_PROMOTED:
            return {}
        return None

    def locate(self, mutant):
        """(node, wrapper kind, range of the wrapped text) of a mutant, or (None, None, None)."""
        op, rng = mutant["operator"], (mutant["begin_offset"], mutant["end_offset"])
        idx = self.index
        if op in BINARY_OPS or op in ("not-removal", "increment"):
            node = idx.operators.get(rng)
            if node is None:
                return None, None, None
            span = idx.gen.span_of(node) or node.get("_operands")
            return (node, "expr", span) if span else (None, None, None)
        if op in ("integer-literal", "char-literal", "enum-constant"):
            kind = {"integer-literal": "IntegerLiteral", "char-literal": "CharacterLiteral",
                    "enum-constant": "DeclRefExpr"}[op]
            node = idx.spans.get((kind, rng[0], rng[1]))
            return (node, "expr", rng) if node else (None, None, None)
        if op == "string-literal":
            for begin, end, node in idx.strings:
                if begin <= rng[0] and rng[1] <= end:
                    return node, "expr", (begin, end)
            return None, None, None
        if op == "condition":
            node = idx.conditions.get(rng)
            return (node, "cond", rng) if node else (None, None, None)
        if op == "return-value":
            node = idx.returns.get(rng)
            return (node, "expr", rng) if node else (None, None, None)
        if op == "statement-deletion":
            node = idx.calls.get(rng)
            return self.statement(node, rng) if node else (None, None, None)
        if op == "function-body":
            node = idx.spans.get(("CompoundStmt", rng[0], rng[1]))
            if node is None or (node.get("_parent") or {}).get("kind") != "FunctionDecl":
                return None, None, None
            return node, "insert", (rng[0] + 1, rng[0] + 1)
        return None, None, None

    def statement(self, node, rng):
        after = self.index.source.skip_blank(rng[1], len(self.data))
        if not self.index.source.token_at(after, b";"):
            return None, None, None
        return node, "stmt", (rng[0], after + 1)

    @staticmethod
    def overlapping(anchors):
        """The anchors whose range overlaps an earlier (in range order) one only partly."""
        bad, stack = [], []
        for anchor in sorted((a for a in anchors if a.kind != "insert"), key=Anchor.key):
            while stack and stack[-1].end <= anchor.begin:
                stack.pop()
            if stack and anchor.end > stack[-1].end:
                bad.append(anchor)
            else:
                stack.append(anchor)
        return bad


def wrap(anchor, inner):
    n = anchor.index
    if anchor.kind == "expr":
        return b"(rigor_hit(%d) ? (%s) : (%s))" % (n, anchor.extra["arm"], inner)
    if anchor.kind == "cond":
        return b"((%s) ? !rigor_hit(%d) : rigor_hit(%d))" % (inner, n, n)
    if anchor.kind == "stmt":
        return b"if (!rigor_hit(%d)) { %s }" % (n, inner)
    body = anchor.mutant["replacement"]
    if not re.search(r"\breturn\b", body):  # v1's body for a void function has no `return`: it replaces the whole body
        body = body[:-1].rstrip() + " return; }"
    return b"if (rigor_hit(%d)) %s" % (n, body.encode("latin-1"))


def nest(anchors):
    """The anchors as a forest, children inside the parent that holds them: [(anchor, [children]...)]."""
    roots, stack = [], []
    for anchor in sorted(anchors, key=Anchor.key):
        while stack and (stack[-1][0].end < anchor.begin or (stack[-1][0].end == anchor.begin and anchor.begin != anchor.end)):
            stack.pop()
        entry = (anchor, [])
        (stack[-1][1] if stack else roots).append(entry)
        if anchor.begin != anchor.end:
            stack.append(entry)
    return roots


def render_node(data, entry):
    anchor, children = entry
    pieces, pos = [], anchor.begin
    for child in children:
        pieces.append(data[pos:child[0].begin])
        pieces.append(render_node(data, child))
        pos = child[0].end
    pieces.append(data[pos:anchor.end])
    return wrap(anchor, b"".join(pieces))


def render(data, anchors):
    """The schema source: the original text with every anchor wrapped. A pure function of the anchor set."""
    out, pos = [PROLOGUE.encode("ascii")], 0
    for entry in nest(anchors):
        out.append(data[pos:entry[0].begin])
        out.append(render_node(data, entry))
        pos = entry[0].end
    out.append(data[pos:])
    return b"".join(out)


class Compiler:
    """Compiles schema sources with the module's command. Counts its compiles."""

    def __init__(self, prefix, rt_include, src_path, scratch):
        self.prefix, self.rt_include, self.src_path, self.scratch = prefix, rt_include, src_path, scratch
        self.count = 0
        self.last_error = ""

    def ok(self, data, anchors, obj=None):
        self.count += 1
        text = render(data, anchors)
        with open(self.src_path, "wb") as handle:
            handle.write(text)
        target = obj or os.path.join(self.scratch, "probe.o")
        done = subprocess.run(self.prefix + ["-iquote", self.rt_include, "-c", self.src_path, "-o", target],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode == 0:
            return True
        if done.returncode < 0 or done.returncode > 1:
            sys.stderr.buffer.write(done.stderr)
            sys.exit("schema.py: the compiler failed with status %d" % done.returncode)
        self.last_error = done.stderr.decode("utf-8", "replace")
        return False


def bisect_unviable(compiler, data, anchors):
    """(anchors that compile together, anchors that were left out). Finds each offender by bisection on the shortest
    failing prefix: with `base` known to compile, the shortest prefix of the rest that fails ends at an offender."""
    base, rest, left_out = [], list(anchors), []
    while rest:
        if compiler.ok(data, base + rest):
            base += rest
            break
        lo, hi = 1, len(rest)
        while lo < hi:
            mid = (lo + hi) // 2
            if compiler.ok(data, base + rest[:mid]):
                lo = mid + 1
            else:
                hi = mid
        left_out.append(rest[lo - 1])
        base += rest[:lo - 1]
        rest = rest[lo:]
    return base, left_out


def build_table(rel, mutants, live, planner, compiler, data, first_index, obj):
    """Plan, number, compile (bisecting if needed) and write the object; returns the table."""
    chosen = [m for m in mutants if m["id"] in live]
    anchors, rejected = planner.plan(chosen)
    eligible = len(anchors)
    for number, anchor in enumerate(anchors):
        anchor.index = first_index + number
    if first_index + len(anchors) - 1 > MAX_INDEX:
        sys.exit("schema.py: %s: %d mutants do not fit the %d of schema_rt.h" % (rel, len(anchors), MAX_INDEX))
    unviable = []
    if not compiler.ok(data, anchors, obj):
        anchors, left_out = bisect_unviable(compiler, data, anchors)
        unviable = [a.mutant["id"] for a in left_out]
        if not compiler.ok(data, anchors, obj):
            sys.exit("schema.py: %s: no schema compiles, even without its offenders:\n%s" % (rel, compiler.last_error))
    counts = {}
    for reason in rejected.values():
        counts[reason] = counts.get(reason, 0) + 1
    if unviable:
        counts[SCHEMA_UNVIABLE] = len(unviable)
    entries = [{"index": a.index, "id": a.mutant["id"], "operator": a.mutant["operator"],
                "function": a.mutant["function"], "line": a.mutant["line"], "kind": a.kind} for a in anchors]
    return {"schema": SCHEMA_TABLE, "file": rel, "live": len(chosen), "eligible": len(entries),
            "entries": entries, "ineligible": dict(sorted(rejected.items())), "unviable": sorted(unviable),
            "reasons": dict(sorted(counts.items())), "compiles": compiler.count, "static_eligible": eligible}


def read_json(path):
    with open(path, "rb") as handle:
        return json.loads(handle.read())


def write_json(path, obj):
    with open(path, "wb") as handle:
        handle.write((json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n").encode())


def cmd_generate(argv):
    command = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(allow_abbrev=False)
    for name in ("src", "gen-json", "live", "gen-py", "rt-include", "out-src", "out-obj", "out-table"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--first-index", type=int, required=True)
    parser.add_argument("--system-root", action="append", default=[])
    args = parser.parse_args(argv)
    if not command:
        sys.exit("schema.py: the module's compile command must follow `--`")
    gen = load_module(args.gen_py, "mutate_gen")
    listing = read_json(args.gen_json)
    with open(args.src, "rb") as handle:
        data = handle.read()
    if hashlib.sha256(data).hexdigest() != listing["sha256"]:
        sys.exit("schema.py: the source is not the one the mutant list was made from")
    done = subprocess.run(command + ["-Xclang", "-ast-dump=json", "-fsyntax-only", args.src], stdout=subprocess.PIPE)
    if done.returncode != 0:
        sys.exit("schema.py: clang failed with status %d" % done.returncode)
    index = AstIndex(gen, json.loads(done.stdout), listing["file"], data, args.system_root)
    with tempfile.TemporaryDirectory(prefix="schema-") as scratch:
        compiler = Compiler(command, args.rt_include, args.out_src, scratch)
        table = build_table(listing["file"], listing["mutants"], set(read_json(args.live)), Planner(index), compiler,
                            data, args.first_index, args.out_obj)
    write_json(args.out_table, table)


COMMANDS = {"generate": cmd_generate}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit("usage: schema.py {%s} ..." % "|".join(COMMANDS))
    COMMANDS[sys.argv[1]](sys.argv[2:])
