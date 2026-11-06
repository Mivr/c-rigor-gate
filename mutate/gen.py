#!/usr/bin/env python3
"""Mutant generator: reads clang's JSON AST of one C source and lists precise text replacements.

Runs inside a Buck2 action on RE (see rules/mutate.bzl), stdlib only:
    gen.py --src PATH --out FILE -- <clang command that prints the JSON AST on stdout>
or, for tests, `gen.py --src PATH --ast FILE --out FILE` (PATH is the source file, FILE its AST).

A mutant is a replacement of source bytes [begin_offset, end_offset) by text. Only AST ranges that
lie in the main file and in no macro expansion are used; a node whose operator token is not found
exactly where the AST says it must be is skipped. Output (canonical JSON):
    {"schema": 1, "file": PATH, "sha256": ..., "definitions": N,
     "functions": [{"name", "line"} + {"reason": "no-mutable-token"} when it has no mutant...],
     "skipped": [{"name", "file", "reason": "macro" | "header"}...],
     "hidden": [{"function", "macro", "line", "defined_in"}...],
     "mutants": [{"id", "file", "begin_offset", "end_offset", "original", "replacement",
                  "operator", "function", "line"}...]}
`skipped` lists functions with a body that no mutant can reach: made by a macro in the main file, or
defined in a header that is not one of the `--system-root` directories (the toolchain's own).
`hidden` lists the uses, inside function bodies that are mutated, of a macro that is not the toolchain's:
code the generator cannot mutate because a macro of the product (in the main file, in a product header,
or on the command line) wrote it (R002 F1; see `Walker.note_macros`). `rigor mutants` makes each a finding.
Accounting invariant (B19): every function definition (a non-implicit `FunctionDecl` with a
`CompoundStmt` child) outside the toolchain's own headers is in exactly one of `functions` and
`skipped`; `definitions` is how many there are, counted by `audit_definitions`, a second walk that
shares no code or state with the walker. The generator exits 2 if the two disagree (by name, not
just by count); `rigor mutants` repeats the comparison on the report.
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
IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
BUILT_IN = "<built-in>"
SCRATCH = "<scratch space>"
OPERATOR_NODES = ("BinaryOperator", "CompoundAssignOperator", "ConditionalOperator")
# Node kinds that decide nothing by themselves, so a macro that only supplies them hides no logic:
# constants, conversions, grouping, names, and declarations (an initializer is a child of its own).
INERT = frozenset(("IntegerLiteral", "CharacterLiteral", "FloatingLiteral", "StringLiteral",
                   "ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "DeclRefExpr", "ConstantExpr",
                   "UnaryExprOrTypeTraitExpr", "PredefinedExpr", "DeclStmt", "VarDecl", "ParmVarDecl",
                   "TypedefDecl", "RecordDecl", "FieldDecl", "EnumDecl", "EnumConstantDecl", "NullStmt",
                   "CompoundLiteralExpr", "InitListExpr"))
# A constant expression is built from these alone: whatever macro writes it, it cannot depend on an input.
CONSTANT_KINDS = frozenset(("IntegerLiteral", "CharacterLiteral", "FloatingLiteral", "StringLiteral",
                            "ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "ConstantExpr",
                            "UnaryExprOrTypeTraitExpr", "BinaryOperator", "UnaryOperator",
                            "ConditionalOperator"))
UNKNOWN_MACRO = "?"
LITERAL = re.compile(rb"(0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)([uUlL]*)")
# Node kinds below which nothing is mutated: constants the language requires (case labels, bit-field
# widths, enumerator values, static assertions) and operands of sizeof, which are not evaluated.
NO_MUTATION = ("ConstantExpr", "StaticAssertDecl", "EnumConstantDecl", "UnaryExprOrTypeTraitExpr",
               "DesignatedInitExpr", "FieldDecl")
CONDITION_SLOT = {"IfStmt": 0, "WhileStmt": 0, "DoStmt": 1, "ForStmt": 2}
NO_MUTABLE_TOKEN = "no-mutable-token"
EXIT_ACCOUNTING = 2


class AccountingError(Exception):
    """A function definition the generator could not account for, or an AST shape it cannot trust."""


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

    def identifier(self, offset):
        """The C identifier that starts at `offset` (the name of a macro at its use), or None."""
        found = IDENTIFIER.match(self.data, offset) if 0 <= offset < len(self.data) else None
        return found.group(0).decode("latin-1") if found else None

    def token_at(self, offset, token):
        return self.data.startswith(token, offset)


def call_end(data, name_end):
    """End of a function-like macro's use whose name ends at `name_end`: just after the matching `)`; the
    name's own end if no `(` follows; None if the parentheses are not balanced in the text."""
    pos = name_end
    while pos < len(data) and data[pos:pos + 1] in (b" ", b"\t", b"\n", b"\r"):
        pos += 1
    if data[pos:pos + 1] != b"(":
        return name_end
    depth = 0
    while pos < len(data):
        byte = data[pos:pos + 1]
        if byte in (b'"', b"'"):
            pos += 1
            while pos < len(data) and data[pos:pos + 1] != byte:
                pos += 2 if data[pos:pos + 1] == b"\\" else 1
        elif data.startswith(b"/*", pos):
            pos = data.find(b"*/", pos + 2)
            if pos < 0:
                return None
            pos += 1
        elif byte == b"(":
            depth += 1
        elif byte == b")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def visible_extent(plain, origin, main_file, data=None, ending=False):
    """(start, end) of the text in the main file that stands for one end of a range: the token itself,
    the argument token the author wrote at a macro call (spelled after the call's name), or, for a
    token the macro makes, the macro's name at its use. None if the main file shows nothing there."""
    if plain is not None:
        return (plain[1], plain[1] + plain[2]) if plain[0] == main_file and plain[1] is not None else None
    if origin is None:
        return None
    spell_file, spell_at, spell_len, exp_file, exp_at, exp_len = origin
    if exp_file != main_file or exp_at is None:
        return None
    if spell_file == main_file and spell_at is not None and spell_at > exp_at:
        return spell_at, spell_at + spell_len
    if ending and data is not None:  # the use of a function-like macro ends at its closing parenthesis
        stop = call_end(data, exp_at + exp_len)
        return None if stop is None else (exp_at, stop)
    return exp_at, exp_at + exp_len


def visible_span(begin, begin_origin, end, end_origin, main_file, data=None):
    """The main-file text an operand seems to occupy, for finding the operator next to it. Unlike `_span` it
    also covers operands that touch a macro (`x < LIMIT`, `assert(a < b)`). It is only used to look for an
    operator token between two operands, which must stand in plain text. A token that a macro makes is shown
    by the macro's use; if an operator is written by the macro itself, both operands are that use, no token
    lies between them, and the miss is a finding."""
    first = visible_extent(begin, begin_origin, main_file)
    last = visible_extent(end, end_origin, main_file, data, ending=True)
    if first is None or last is None or last[1] < first[0]:
        return None
    return first[0], last[1]


def annotate(root, main_file, data=None):
    """Store `_span` on every node: the byte range [begin, end) if both ends are plain main-file
    locations, else None, and `_where` (file, in a macro expansion) of its `loc`. Returns whether
    any location named the main file. The walk follows clang's print order, which fixes what an elided `file`
    means (the dump only names a file when it differs from the previous location it printed)."""
    state = {"file": "", "main_seen": False}

    def bare(loc):
        if "file" in loc:
            state["file"] = loc["file"]
        state["main_seen"] = state["main_seen"] or state["file"] == main_file
        return state["file"], loc.get("offset"), loc.get("tokLen", 0)

    def point(loc):
        if "spellingLoc" in loc or "expansionLoc" in loc:
            places = [bare(loc[part]) for part in ("spellingLoc", "expansionLoc") if part in loc]
            origin = None
            if "spellingLoc" in loc and "expansionLoc" in loc:
                origin = places[0] + places[1]
            return None, places[-1][0], origin
        return bare(loc), None, None

    def visit(node):
        if not isinstance(node, dict):
            return
        node["_span"] = None
        origins = []
        if "loc" in node:
            plain, expanded, origin = point(node["loc"])
            node["_where"] = (plain[0] if plain else expanded, plain is None)
            node["_name_in_macro"] = plain is None
            origins.append(("loc", origin))
        if "range" in node:
            begin, _, begin_origin = point(node["range"]["begin"])
            end, _, end_origin = point(node["range"]["end"])
            node["_xspan"] = visible_span(begin, begin_origin, end, end_origin, main_file, data)
            origins.extend((("begin", begin_origin), ("end", end_origin)))
            if begin and end and begin[0] == main_file and end[0] == main_file \
                    and begin[1] is not None and end[1] is not None and begin[2] and end[2] \
                    and end[1] + end[2] >= begin[1]:
                node["_span"] = (begin[1], end[1] + end[2])
        node["_origins"] = [(part,) + o for part, o in origins if o is not None]
        node.setdefault("_xspan", None)
        for child in node.get("inner", []):
            visit(child)

    visit(root)
    return state["main_seen"]


def operand_span(node):
    return (span_of(node) or node.get("_xspan")) if isinstance(node, dict) else None


def span_of(node):
    return node.get("_span") if isinstance(node, dict) else None


class Walker:
    def __init__(self, source, main_file, system_roots=()):
        self.source = source
        self.main = main_file
        self.system_roots = tuple(system_roots)
        self.mutants = []
        self.functions = []
        self.skipped = []  # functions with a body that no mutant can reach, and why
        self.system = []  # names of definitions in the toolchain's own headers (reported nowhere)
        self.hidden = []  # code in live function bodies that a product macro makes (R002 F1)
        self.hidden_seen = set()
        self.known_system = set()  # macros seen with a token spelled in the toolchain's headers
        self.pasted = []  # (function, macro, offset) of tokens made by ## or #, spelled nowhere

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
        elif kind == "StmtExpr":
            for child in children:  # its last statement is the value: never replace it by (void)0
                if isinstance(child, dict) and child.get("kind") == "CompoundStmt":
                    child["_value_last"] = True
        if ctx["function"] is not None and ctx["live"]:
            self.note_macros(node, ctx)
            if span_of(node) is not None or (kind in OPERATOR_NODES and not constant_tree(node)):
                self.mutate(node, kind, children, ctx)  # an operator is found from its operands' text
        for child in children:
            self.visit(child, child_ctx)

    def enter_function(self, node, ctx):
        bodies = [c for c in node.get("inner", []) if isinstance(c, dict) and c.get("kind") == "CompoundStmt"]
        if len(bodies) > 1:
            raise AccountingError("function %r has %d compound statements; the body is not unique"
                                  % (node.get("name", ""), len(bodies)))
        if not bodies or node.get("isImplicit"):
            return ctx
        body = bodies[0]  # wherever it sits: attributes may follow it
        if span_of(body) is None or node.get("_name_in_macro"):
            # Made by a macro, or defined in a header: the body, or the function's name, does not
            # lie in plain main-file text. (A node whose range merely *starts* in a macro, `bool f(void)
            # { ... }` or `NOINLINE int f(void) { ... }`, is not that: the decision is taken from the
            # name's location and the body's span, never from `range.begin`.)
            self.skip(node)
            return ctx
        params = [c.get("name") for c in node["inner"] if c.get("kind") == "ParmVarDecl"]
        name = node.get("name", "")
        self.functions.append({"name": name, "line": self.source.line((span_of(node) or span_of(body))[0])})
        return {"function": name, "params": [p for p in params if p], "live": True,
                "qual": node.get("type", {}), "body": body}

    def skip(self, node):
        """A function with a body that is not in the main file, or is made by a macro, can not be
        mutated: record it unless it comes from the toolchain's own headers."""
        file = node.get("_where", (self.main,))[0]
        if file == self.main:
            reason = "macro"
        elif in_roots(file, self.system_roots):
            self.system.append(node.get("name", ""))
            return
        else:
            reason = "header"
        self.skipped.append({"name": node.get("name", ""), "file": file, "reason": reason})

    def note_macros(self, node, ctx):
        """Record every use of a product macro that makes a part of this node (R002 F1).

        A location that is a macro expansion has a spelling place (where the token was written) and an
        expansion place (the use, in the main file). The token is the macro's own, and the code is
        hidden from mutation, unless its spelling is
        - in a toolchain header (`NULL`, `bool`, `INT32_MAX`, `offsetof`, `assert` ...: not a finding),
        - in the compiler's `<built-in>` buffer (`__LINE__`), or
        - in the main file *after* the use's start: a macro definition precedes every use of it, so
          such a token is an argument, text the author wrote at the call site, which is mutated like any.
        A token made by `##` or `#` is spelled in `<scratch space>`, which names no macro: it is a
        finding unless the same macro is shown to be the toolchain's by another of its tokens (`finish`).
        Everything else (a body in the main file or in a product header, `<command line>`) is a finding,
        in the function that contains the use. Nodes that cannot decide anything by themselves (a
        literal, a cast, a parenthesis, a name, a declaration, an attribute) are not looked at: what
        they enclose is."""
        kind = node.get("kind", "")
        if kind in INERT or kind in OPERATOR_NODES or kind.endswith("Attr") or constant_tree(node):
            return  # (an operator is judged by `operator_between`: it is found next to its operands or reported)
        for part, spell_file, spell_at, _, exp_file, exp_at, _ in node.get("_origins", ()):
            if kind == "ReturnStmt" and part == "end":
                continue  # `return LIMIT;`: the value is a child of its own; `return` itself is at begin
            here = exp_file == self.main and exp_at is not None
            name = self.source.identifier(exp_at) if here else None
            if in_roots(spell_file, self.system_roots):
                self.known_system.add(name)
            elif spell_file == BUILT_IN:
                continue
            elif spell_file == SCRATCH:
                self.pasted.append((ctx["function"], name or UNKNOWN_MACRO, exp_at if here else None))
            elif not (spell_file == self.main and here and spell_at is not None and spell_at > exp_at):
                self.record_hidden(ctx["function"], name or UNKNOWN_MACRO, exp_at if here else None, spell_file)

    def finish(self):
        """Pasted tokens of a macro that no other token proves to be the toolchain's are findings."""
        for function, macro, at in self.pasted:
            if macro not in self.known_system:
                self.record_hidden(function, macro, at, SCRATCH)

    def record_hidden(self, function, macro, at, defined_in):
        key = (function, macro, at, defined_in if at is None else "")
        if key not in self.hidden_seen:
            self.hidden_seen.add(key)
            self.hidden.append({"function": function, "macro": macro,
                                "line": self.source.line(at) if at is not None else 0,
                                "defined_in": defined_in})

    def mutate(self, node, kind, children, ctx):
        span = span_of(node)
        if kind == "ConditionalOperator":
            self.ternary(node, children, ctx)
        elif kind == "BinaryOperator":
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
            self.deletions(children[:-1] if node.get("_value_last") else children, ctx)
            if node is ctx["body"]:
                self.whole_body(span, ctx)

    def operator_between(self, node, children, ctx, operator, table):
        opcode = node.get("opcode")
        if opcode not in table or len(children) != 2:
            return
        lhs, rhs = operand_span(children[0]), operand_span(children[1])
        if lhs is None or rhs is None:
            self.operator_missing(opcode, None, ctx, node, children)
            return
        at = self.source.token_between(lhs[1], rhs[0], opcode.encode("ascii"))
        if at is None:
            self.operator_missing(opcode, lhs[1], ctx, node, children)
            return
        for replacement in table[opcode]:
            self.add(ctx, operator, at, at + len(opcode), replacement)

    def ternary(self, node, children, ctx):
        """`c ? a : b` has no mutation of its own, but its `?` and `:` must be written between the operands
        like any plain text; if a macro supplies them, that is a finding (as for any operator)."""
        spans = [operand_span(c) for c in children]
        if len(spans) != 3 or None in spans:
            self.operator_missing("?:", None, ctx, node, children)
            return
        for token, left, right in ((b"?", spans[0], spans[1]), (b":", spans[1], spans[2])):
            if self.source.token_between(left[1], right[0], token) is None:
                self.operator_missing(token.decode(), left[1], ctx, node, children)
                return

    def operator_missing(self, opcode, after, ctx, node, children):
        """Both operands are visible but the operator is not written between them: a macro supplies it
        (`a PLUS b`, `SUM(a, b)`), and the AST does not say where an operator is. Fail closed: a finding,
        unless the toolchain's own macro supplies it (its tokens are spelled in a system header)."""
        if any(in_roots(o[1], self.system_roots) or o[1] == BUILT_IN for o in node.get("_origins", ())):
            return
        macro, at, defined_in = self.operand_macro(children)
        if macro is None and after is not None:
            at = self.source.skip_blank(after, len(self.source.data))
            macro = self.source.identifier(at)
        self.record_hidden(ctx["function"], macro or UNKNOWN_MACRO, at if macro else None,
                           defined_in or "<operator %s not found between its operands>" % opcode)

    def operand_macro(self, children):
        """(name, use offset, file of its tokens) of a macro, not the toolchain's, whose own tokens an
        operand shows; (None, None, None) if there is none."""
        for child in children:
            for _, spell_file, spell_at, _, exp_file, exp_at, _ in child.get("_origins", ()) \
                    if isinstance(child, dict) else ():
                if exp_file == self.main and exp_at is not None and not in_roots(spell_file, self.system_roots) \
                        and not (spell_file == self.main and spell_at is not None and spell_at > exp_at):
                    return self.source.identifier(exp_at), exp_at, spell_file
        return None, None, None

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
        cond = children[slot] if len(children) > slot else {}
        span = span_of(cond) if isinstance(cond, dict) and "valueCategory" in cond else None
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


def constant_tree(node):
    """True if the whole subtree is a constant expression: literals, `sizeof`, enumerators and the
    operators between them. Such text decides nothing about an input, so a macro writing it hides no logic
    (its operators still cannot be mutated: that is a limit, not a finding)."""
    if "_constant" not in node:
        kind = node.get("kind", "")
        if kind == "DeclRefExpr":
            node["_constant"] = node.get("referencedDecl", {}).get("kind") == "EnumConstantDecl"
        elif kind == "UnaryExprOrTypeTraitExpr":
            node["_constant"] = True
        elif kind not in CONSTANT_KINDS or (kind == "UnaryOperator" and node.get("opcode") in ("++", "--")):
            node["_constant"] = False
        else:
            node["_constant"] = all(constant_tree(c) for c in node.get("inner", []) if isinstance(c, dict))
    return node["_constant"]


def in_roots(file, roots):
    return any(file == root or file.startswith(root + "/") for root in roots)


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


def audit_definitions(ast, system_roots):
    """(names outside the toolchain's headers, names inside them) of every function definition in the AST.

    The second, independent count behind the accounting invariant: it shares nothing with `Walker`
    (no `annotate`, no `_span`, no context, no `enter_function`). It walks the raw JSON in document
    order, which is clang's print order, so it follows the file a location names (a location that names
    none is in the file of the last one printed). A definition is any non-implicit FunctionDecl with a
    CompoundStmt among its children, wherever among them, and a macro-made one counts in the file the
    macro was expanded in."""
    state = {"file": ""}
    outside = []
    inside = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        here = None
        for key, child in value.items():
            if key == "includedFrom":
                continue  # names the includer, not the file of this location
            if key == "file" and isinstance(child, str):
                state["file"] = child
            else:
                walk(child)
            if key == "loc":
                here = state["file"]
        children = value.get("inner")
        if value.get("kind") == "FunctionDecl" and not value.get("isImplicit") \
                and isinstance(children, list) \
                and any(isinstance(c, dict) and c.get("kind") == "CompoundStmt" for c in children):
            (inside if in_roots(here if here is not None else state["file"], system_roots)
             else outside).append(value.get("name", ""))

    walk(ast)
    return sorted(outside), sorted(inside)


def check_accounting(walker, ast):
    """Fail closed unless the walker and `audit_definitions` agree on every definition, by name."""
    outside, inside = audit_definitions(ast, walker.system_roots)
    accounted = sorted([f["name"] for f in walker.functions] + [s["name"] for s in walker.skipped])
    problems = []
    if accounted != outside:
        problems.append("definitions in the AST %r, accounted for %r" % (outside, accounted))
    if sorted(walker.system) != inside:
        problems.append("toolchain definitions in the AST %r, passed over %r" % (inside, sorted(walker.system)))
    if problems:
        raise AccountingError("; ".join(problems))
    return len(outside)


def generate(file_path, data, ast, system_roots=()):
    if not annotate(ast, file_path, data) and data.strip():
        raise SystemExit("gen.py: no location in the AST names %r; the generator would be blind"
                         % file_path)
    source = Source(data)
    walker = Walker(source, file_path, system_roots)
    for top in ast.get("inner", []):
        walker.visit(top, {"function": None, "live": True})
    walker.finish()
    definitions = check_accounting(walker, ast)
    mutants = assign_ids(walker.mutants, file_path)
    mutated = {m["function"] for m in mutants}
    functions = [dict(f, reason=NO_MUTABLE_TOKEN) if f["name"] not in mutated else f
                 for f in walker.functions]
    return {"schema": SCHEMA, "file": file_path, "sha256": hashlib.sha256(data).hexdigest(),
            "definitions": definitions, "functions": functions, "skipped": walker.skipped,
            "hidden": sorted(walker.hidden, key=lambda h: (h["line"], h["macro"], h["function"], h["defined_in"])),
            "mutants": mutants}


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
    parser.add_argument("--system-root", action="append", default=[])
    args = parser.parse_args(argv)
    if bool(args.ast) == bool(command):
        sys.exit("gen.py: give either --ast FILE or a clang command after --")
    with open(args.src, "rb") as handle:
        data = handle.read()
    try:
        result = generate(args.src, data, read_ast(args.ast, command), args.system_root)
    except AccountingError as exc:
        sys.stderr.write("gen.py: accounting failed for %s: %s\n" % (args.src, exc))
        sys.exit(EXIT_ACCOUNTING)
    with open(args.out, "wb") as handle:
        handle.write(canonical(result))


if __name__ == "__main__":
    main(sys.argv[1:])
