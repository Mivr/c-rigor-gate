"""Text scans of C sources for gate `decoupling`: no compiler, the same answer in a grade and in the baseline tool.

`strip` removes comments (and joins line splices); `includes` lists the `#include` operands; `identifiers` the
identifier tokens outside string and character literals; `declarations` cuts a header into its top-level
declarations for the frozen-interface comparison. Nothing here expands a macro or evaluates an `#if`: a
conditional include counts as an include, a name inside `#if 0` as a name (docs/decoupling.md, blind spots).
"""

import re

_INCLUDE = re.compile(r'[ \t]*#[ \t]*include[ \t]*(?:"([^"\n]+)"|<([^>\n]+)>)')
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|[0-9][A-Za-z_0-9.]*|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|\S")
_DEFINE = re.compile(r"# (define|undef) ([A-Za-z_][A-Za-z_0-9]*)")
_SPLICE = "\x00"


def _literal_end(text, start):
    """Index after the string or character literal that starts at `start` (the end of its line if unterminated)."""
    quote, i, size = text[start], start + 1, len(text)
    while i < size and text[i] != "\n":
        if text[i] == "\\":
            i += 2
        elif text[i] == quote:
            return i + 1
        else:
            i += 1
    return min(i, size)


def _spliced(text):
    """Line splices joined; each leaves the mark `_SPLICE`, which `_unmark` turns into a newline after the line."""
    return text.replace("\\\r\n", _SPLICE).replace("\\\n", _SPLICE)


def _unmark(text):
    lines = []
    for line in text.split("\n"):
        lines.append(line.replace(_SPLICE, "") + "\n" * line.count(_SPLICE))
    return "\n".join(lines)


def strip(text, literals=True):
    """The text with line splices joined and every comment replaced by one space. A joined line is followed by as
    many empty lines as it had splices and a block comment keeps its newlines, so line numbers hold.
    `literals=False` also empties string and character literals."""
    text = _spliced(text.replace(_SPLICE, " "))
    out, i, size = [], 0, len(text)
    while i < size:
        two = text[i:i + 2]
        if two == "//":
            end = text.find("\n", i)
            end = size if end < 0 else end
            out.append(" " + _SPLICE * text.count(_SPLICE, i, end))
            i = end
        elif two == "/*":
            end = text.find("*/", i + 2)
            end = size if end < 0 else end + 2
            out.append(" " + "\n" * text.count("\n", i, end) + _SPLICE * text.count(_SPLICE, i, end))
            i = end
        elif text[i] in "\"'":
            end = _literal_end(text, i)
            out.append(text[i:end] if literals else text[i] * 2 + _SPLICE * text.count(_SPLICE, i, end))
            i = end
        else:
            out.append(text[i])
            i += 1
    return _unmark("".join(out))


def includes(text):
    """The operands of every `#include "x"` and `#include <x>` line, in order (a macro operand is not seen)."""
    found = []
    for line in strip(text).split("\n"):
        match = _INCLUDE.match(line)
        if match:
            found.append(match.group(1) or match.group(2))
    return found


def identifiers(text):
    """Every identifier token outside comments and literals (keywords and macro names included)."""
    return frozenset(_IDENTIFIER.findall(strip(text, literals=False)))


def _is_function_body(tokens):
    """Does the `{` about to be read open a function body? (The declaration so far ends with `)`.)"""
    return bool(tokens) and tokens[-1] == ")"


def declarations(text):
    """[(line, text)]: the top-level declarations of a header, each as its tokens joined by one space.

    A preprocessor line is one declaration (`# define X 1`: runs of blanks folded). Other text is cut at a `;` outside every brace and parenthesis, and
    after the closing brace of a function body. `line` is where the declaration starts.
    """
    found, tokens, start, depth, body = [], [], 0, 0, None

    def close():
        nonlocal tokens, body
        if tokens:
            found.append((start, " ".join(tokens)))
        tokens, body = [], None

    for number, line in enumerate(strip(text).split("\n"), 1):
        words = _TOKEN.findall(line)
        if not words:
            continue
        if words[0] == "#" and depth == 0 and not tokens:
            # Blanks matter in a directive (`#define M(a)` is not `#define M (a)`): only their runs are folded.
            found.append((number, "# " + " ".join(line.split())[1:].lstrip()))
            continue
        for word in words:
            if not tokens:
                start = number
            if word in "{(":
                if word == "{" and depth == 0 and _is_function_body(tokens):
                    body = True
                depth += 1
            elif word in "})":
                depth = max(0, depth - 1)
            tokens.append(word)
            if depth == 0 and (word == ";" or (word == "}" and body)):
                close()
    close()
    return found


def defined_name(declaration):
    """The macro a `#define X`/`#undef X` declaration names, or None."""
    match = _DEFINE.match(declaration)
    return match.group(2) if match else None
