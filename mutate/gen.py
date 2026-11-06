#!/usr/bin/env python3
"""Mutant generator: reads clang's JSON AST of one C source and lists precise text replacements.

Runs inside a Buck2 action on RE (see rules/mutate.bzl), stdlib only:
    gen.py --src PATH --out FILE -- <clang command that prints the JSON AST on stdout>
or, for tests, `gen.py --src PATH --ast FILE --out FILE` (PATH is the source file, FILE its AST).

A mutant is a replacement of source bytes [begin_offset, end_offset) by text. Only AST ranges that
lie in the main file and in no macro expansion are used; a node whose operator token is not found
exactly where the AST says it must be is skipped. Output (canonical JSON):
    {"schema": 1, "file": PATH, "sha256": ..., "functions": [{"name", "line"}...],
     "mutants": [{"id", "file", "begin_offset", "end_offset", "original", "replacement",
                  "operator", "function", "line"}...]}
`original` and `replacement` are the bytes decoded as latin-1 (lossless). Mutants are sorted by
(begin, end, replacement, operator). The id is the first 16 hex digits of sha256 over
file, function, operator, original, replacement and the ordinal among equal ones in the function.
"""

import argparse
import bisect
import hashlib
import json
import re
import subprocess
import sys

SCHEMA = 1
sys.setrecursionlimit(20000)

# Operator tables: opcode -> replacements. Each row is one operator family.
RELATIONAL = {"<": ["<=", ">="], "<=": ["<", ">"], ">": [">=", "<="], ">=": [">", "<"],
              "==": ["!="], "!=": ["=="]}
ARITHMETIC = {"+": ["-"], "-": ["+"], "*": ["/"], "/": ["*"], "%": ["*"], "<<": [">>"],
              ">>": ["<<"], "&": ["|"], "|": ["&"], "^": ["&"]}
LOGICAL = {"&&": ["||"], "||": ["&&"]}
COMPOUND = {"+=": ["-="], "-=": ["+="], "*=": ["/="], "/=": ["*="], "%=": ["*="], "<<=": [">>="],
            ">>=": ["<<="], "&=": ["|="], "|=": ["&="], "^=": ["&="]}
INCREMENT = {"++": "--", "--": "++"}
BINARY_TABLES = (("relational", RELATIONAL), ("arithmetic", ARITHMETIC), ("logical", LOGICAL))
OPERATORS = ("relational", "arithmetic", "logical", "not-removal", "compound-assignment",
             "increment", "integer-literal", "condition", "return-value", "statement-deletion",
             "function-body")
LITERAL = re.compile(rb"(0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)([uUlL]*)")
# Node kinds below which nothing is mutated: constants the language requires (case labels, bit-field
# widths, enumerator values, static assertions) and operands of sizeof, which are not evaluated.
NO_MUTATION = ("ConstantExpr", "StaticAssertDecl", "EnumConstantDecl", "UnaryExprOrTypeTraitExpr",
               "DesignatedInitExpr", "FieldDecl")
CONDITION_SLOT = {"IfStmt": 0, "WhileStmt": 0, "DoStmt": 1, "ForStmt": 2}


class Source:
    """The main file's bytes, with line lookup and a comment-aware token finder."""

    def __init__(self, data):
        self.data = data
        self.newlines = [i for i, byte in enumerate(data) if byte == 10]

    def line(self, offset):
        return bisect.bisect_left(self.newlines, offset) + 1

    def skip_blank(self, pos, stop):
        """First position at or after `pos` that is not whitespace, a comment or a line splice."""
        data = self.data
        while pos < stop:
            if data[pos:pos + 1] in (b" ", b"\t", b"\n", b"\r", b"\f", b"\v"):
                pos += 1
            elif data.startswith(b"\\\n", pos):
                pos += 2
            elif data.startswith(b"/*", pos):
                end = data.find(b"*/", pos + 2)
                if end < 0 or end + 2 > stop:
                    return stop
                pos = end + 2
            elif data.startswith(b"//", pos):
                end = data.find(b"\n", pos)
                pos = stop if end < 0 else end + 1
            else:
                break
        return pos

    def token_between(self, start, stop, token):
        """Offset of `token` if it is the only thing in [start, stop) besides blanks, else None."""
        pos = self.skip_blank(start, stop)
        if not self.data.startswith(token, pos) or pos + len(token) > stop:
            return None
        if self.skip_blank(pos + len(token), stop) != stop:
            return None
        return pos

    def token_at(self, offset, token):
        return self.data.startswith(token, offset)


def annotate(root, main_file):
    """Store `_span` on every node: the byte range [begin, end) if both ends are plain main-file
    locations, else None. The walk follows clang's print order, which fixes what an elided `file`
    means (the dump only names a file when it differs from the previous location it printed)."""
    state = {"file": ""}

    def bare(loc):
        if "file" in loc:
            state["file"] = loc["file"]
        return state["file"], loc.get("offset"), loc.get("tokLen", 0)

    def point(loc):
        if "spellingLoc" in loc or "expansionLoc" in loc:
            for part in ("spellingLoc", "expansionLoc"):
                if part in loc:
                    bare(loc[part])
            return None
        return bare(loc)

    def visit(node):
        if not isinstance(node, dict):
            return
        node["_span"] = None
        if "loc" in node:
            point(node["loc"])
        if "range" in node:
            begin = point(node["range"]["begin"])
            end = point(node["range"]["end"])
            if begin and end and begin[0] == main_file and end[0] == main_file \
                    and begin[1] is not None and end[1] is not None and begin[2] and end[2] \
                    and end[1] + end[2] >= begin[1]:
                node["_span"] = (begin[1], end[1] + end[2])
        for child in node.get("inner", []):
            visit(child)

    visit(root)


def span_of(node):
    return node.get("_span") if isinstance(node, dict) else None


class Walker:
    def __init__(self, source, main_file):
        self.source = source
        self.main = main_file
        self.mutants = []
        self.functions = []

    def add(self, ctx, operator, begin, end, replacement):
        original = self.source.data[begin:end]
        if original == replacement.encode("latin-1") or not 0 <= begin <= end <= len(self.source.data):
            return
        self.mutants.append({
            "file": self.main, "begin_offset": begin, "end_offset": end,
            "original": original.decode("latin-1"), "replacement": replacement,
            "operator": operator, "function": ctx["function"], "line": self.source.line(begin),
        })

    def visit(self, node, ctx):
        if not isinstance(node, dict) or not node:
            return
        kind = node.get("kind", "")
        children = node.get("inner", [])
        child_ctx = ctx
        if kind == "FunctionDecl":
            child_ctx = self.enter_function(node, ctx)
        elif kind in NO_MUTATION:
            child_ctx = dict(ctx, live=False)
        if ctx["function"] is not None and ctx["live"] and span_of(node) is not None:
            self.mutate(node, kind, children, ctx)
        for child in children:
            self.visit(child, child_ctx)

    def enter_function(self, node, ctx):
        body = node["inner"][-1] if node.get("inner") else None
        if span_of(node) is None or not body or body.get("kind") != "CompoundStmt" \
                or node.get("isImplicit"):
            return ctx
        params = [c.get("name") for c in node["inner"] if c.get("kind") == "ParmVarDecl"]
        name = node.get("name", "")
        self.functions.append({"name": name, "line": self.source.line(span_of(node)[0])})
        return {"function": name, "params": [p for p in params if p], "live": True,
                "qual": node.get("type", {}), "body": body}

    def mutate(self, node, kind, children, ctx):
        span = span_of(node)
        if kind == "BinaryOperator":
            self.binary(node, children, ctx)
        elif kind == "UnaryOperator":
            self.unary(node, span, ctx)
        elif kind == "CompoundAssignOperator":
            self.operator_between(node, children, ctx, "compound-assignment", COMPOUND)
        elif kind == "IntegerLiteral":
            self.literal(span, ctx)
        elif kind in CONDITION_SLOT:
            self.condition(kind, children, ctx)
        elif kind == "ReturnStmt":
            self.returned(children, ctx)
        elif kind == "CompoundStmt":
            self.deletions(children, ctx)
            if node is ctx["body"]:
                self.whole_body(span, ctx)

    def operator_between(self, node, children, ctx, operator, table):
        opcode = node.get("opcode")
        if opcode not in table or len(children) != 2:
            return
        lhs, rhs = span_of(children[0]), span_of(children[1])
        if lhs is None or rhs is None:
            return
        at = self.source.token_between(lhs[1], rhs[0], opcode.encode("ascii"))
        if at is None:
            return
        for replacement in table[opcode]:
            self.add(ctx, operator, at, at + len(opcode), replacement)

    def binary(self, node, children, ctx):
        opcode = node.get("opcode")
        for operator, table in BINARY_TABLES:
            if opcode in table:
                if opcode in ("+", "-") and any(pointerish(c) for c in children):
                    return
                self.operator_between(node, children, ctx, operator, table)
                return

    def unary(self, node, span, ctx):
        opcode = node.get("opcode")
        if opcode == "!":
            if self.source.token_at(span[0], b"!"):
                self.add(ctx, "not-removal", span[0], span[0] + 1, "")
        elif opcode in INCREMENT:
            at = span[1] - 2 if node.get("isPostfix") else span[0]
            if self.source.token_at(at, opcode.encode("ascii")):
                self.add(ctx, "increment", at, at + 2, INCREMENT[opcode])

    def literal(self, span, ctx):
        found = LITERAL.fullmatch(self.source.data[span[0]:span[1]])
        if not found:
            return
        digits, suffix = found.group(1), found.group(2).decode("ascii")
        hexa = digits[:2] in (b"0x", b"0X")
        value = int(digits, 16 if hexa else 10)
        if value == 0:
            new = "0x1" if hexa else "1"
        elif value == 1 and not hexa:
            new = "0"
        else:
            new = ("0x%x" % (value + 1)) if hexa else str(value + 1)
        self.add(ctx, "integer-literal", span[0], span[1], new + suffix)

    def condition(self, kind, children, ctx):
        slot = CONDITION_SLOT[kind]
        span = span_of(children[slot]) if len(children) > slot else None
        if span is not None:
            original = self.source.data[span[0]:span[1]].decode("latin-1")
            self.add(ctx, "condition", span[0], span[1], "!(" + original + ")")

    def returned(self, children, ctx):
        if len(children) != 1:
            return
        typ = children[0].get("type", {})
        text = typ.get("qualType", "")
        deep = typ.get("desugaredQualType", text)
        if not text or "complex" in text.lower() or deep == "void" \
                or text.startswith(("struct ", "union ")) or deep.startswith(("struct ", "union ")):
            return
        span = span_of(children[0])
        if span is None:
            return
        original = self.source.data[span[0]:span[1]].decode("latin-1")
        value = "1" if original == "0" else "0"
        if children[0].get("kind") != "IntegerLiteral":
            # Keep evaluating the expression: its parameters and variables stay used.
            value = "((void)(%s), (%s)%s)" % (original, text, value)
        self.add(ctx, "return-value", span[0], span[1], value)

    def deletions(self, children, ctx):
        for child in children:
            span = span_of(child)
            if span is None or child.get("kind") != "CallExpr":
                continue
            after = self.source.skip_blank(span[1], len(self.source.data))
            if self.source.token_at(after, b";"):
                self.add(ctx, "statement-deletion", span[0], span[1], "(void)0")

    def whole_body(self, span, ctx):
        qual = ctx["qual"]
        returns = return_class(qual.get("desugaredQualType", qual.get("qualType", "")))
        if returns is None or not self.source.token_at(span[0], b"{"):
            return
        uses = "".join("(void)%s; " % name for name in ctx["params"])
        self.add(ctx, "function-body", span[0], span[1],
                 "{ " + uses + ("}" if returns == "void" else "return 0; }"))


def pointerish(node):
    typ = node.get("type", {})
    both = typ.get("qualType", "") + " " + typ.get("desugaredQualType", "")
    return "*" in both or "[" in both


def return_class(function_type):
    """'void', 'scalar' or None (struct, union, complex, function pointer returns) from "R (P)"."""
    text = function_type.strip()
    if not text.endswith(")"):
        return None
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(text[index], 0)
        if depth == 0:
            text = text[:index].strip()
            break
    else:
        return None
    for word in ("static", "inline", "extern", "const", "volatile", "restrict"):
        text = re.sub(r"\b%s\b" % word, "", text).strip()
    if "(" in text or "complex" in text.lower() or text.startswith(("struct ", "union ")) or not text:
        return None
    return "void" if text == "void" else "scalar"


def assign_ids(mutants, file_path):
    """Sort, keep one mutant per text change, and compute the stable ids."""
    mutants.sort(key=lambda m: (m["begin_offset"], m["end_offset"], m["replacement"],
                                OPERATORS.index(m["operator"])))
    seen_change = set()
    seen_group = {}
    result = []
    for mutant in mutants:
        change = (mutant["begin_offset"], mutant["end_offset"], mutant["replacement"])
        if change in seen_change:
            continue
        seen_change.add(change)
        group = (mutant["function"], mutant["operator"], mutant["original"], mutant["replacement"])
        ordinal = seen_group.get(group, 0)
        seen_group[group] = ordinal + 1
        material = "\0".join((file_path,) + group + (str(ordinal),))
        mutant["id"] = hashlib.sha256(material.encode("latin-1")).hexdigest()[:16]
        result.append(mutant)
    return result


def generate(file_path, data, ast):
    annotate(ast, file_path)
    source = Source(data)
    walker = Walker(source, file_path)
    for top in ast.get("inner", []):
        walker.visit(top, {"function": None, "live": True})
    return {"schema": SCHEMA, "file": file_path, "sha256": hashlib.sha256(data).hexdigest(),
            "functions": walker.functions, "mutants": assign_ids(walker.mutants, file_path)}


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def read_ast(path, command):
    if path:
        with open(path, "rb") as handle:
            return json.loads(handle.read())
    done = subprocess.run(command, stdout=subprocess.PIPE)
    if done.returncode != 0:
        sys.exit("gen.py: clang failed with status %d" % done.returncode)
    return json.loads(done.stdout)


def main(argv):
    command = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ast")
    args = parser.parse_args(argv)
    if bool(args.ast) == bool(command):
        sys.exit("gen.py: give either --ast FILE or a clang command after --")
    with open(args.src, "rb") as handle:
        data = handle.read()
    result = generate(args.src, data, read_ast(args.ast, command))
    with open(args.out, "wb") as handle:
        handle.write(canonical(result))


if __name__ == "__main__":
    main(sys.argv[1:])
