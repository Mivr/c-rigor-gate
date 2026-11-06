"""String literals that inline code (Python, Node, Ruby, Perl, ...) hands to a file or process call.

Text fed to an interpreter is code, but only a string used as a path or a command can touch a forbidden
location. A path that merely appears in a docstring, a comment, a `print` or a text being edited is not an
access, so `rigor trajectory` looks at literals in the arguments of calls that open, list, move, delete or
run something, and at the literals those arguments name through a simple `name = "literal"` assignment.
"""

import re

_STRING = (r"(?:[rRbBuUfF]{1,2})?(?:'''(?:[^\\]|\\.)*?'''|\"\"\"(?:[^\\]|\\.)*?\"\"\""
           r"|'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")")
_STRING_RE = re.compile(_STRING, re.DOTALL)
_ASSIGN_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*(?::[^=\n]*)?=(?!=)\s*(" + _STRING + ")", re.DOTALL)
_NAME_RE = re.compile(r"[A-Za-z_]\w*")
_CALL_RE = re.compile(
    r"(?<![\w$])(?:(?:File|IO|Dir|FileUtils|Pathname)\.\w+|(?:[A-Za-z_]\w*\.)*(?:open|fopen|opendir|read_text|"
    r"write_text|read_bytes|write_bytes|Path|PurePath|PosixPath|listdir|scandir|walk|iterdir|glob|iglob|rglob|"
    r"stat|lstat|exists|isfile|isdir|access|chdir|remove|unlink|rmdir|rename|makedirs|mkdir|copy2|copyfile|"
    r"copytree|move|rmtree|symlink|readlink|realpath|system|popen|run|call|Popen|check_output|check_call|"
    r"spawn|spawnSync|exec|execSync|execFile|execFileSync|readFile|readFileSync|writeFile|writeFileSync|"
    r"appendFile|readdir|readdirSync|createReadStream|createWriteStream|readlines|chdir|require|import|"
    r"__import__|exec|eval))\s*\(")
_MAX_ARGS = 4000
_PREFIX_RE = re.compile(r"[A-Za-z]*")
_DATA_CALLS = ("write_text", "write_bytes")  # their arguments are the text written, never a path
_COMMENT_RE = re.compile(r"(?:(?<=\s)|\A)#[^\n]*")


def _inert_spans(text, comments=False):
    """(start, end) of the string literals of `text` that are only data: not f-strings (code runs inside
    their braces), not inside a comment. Scanned left to right so that quotes in a comment, or inside
    another string, do not start a string of their own. With `comments`, `#` comments are spans too."""
    spans, i = [], 0
    while i < len(text):
        if text[i] in "'\"" or text[i] in "rRbBuUfF" and i + 1 < len(text) and (
                text[i + 1] in "'\"" or text[i + 1] in "rRbBuUfF"):
            match = _STRING_RE.match(text, i)
            if match is not None and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                if "f" not in _PREFIX_RE.match(match.group(0)).group(0).lower():
                    spans.append((match.start(), match.end()))
                i = match.end()
                continue
        elif text[i] == "#" and (i == 0 or text[i - 1].isspace()):
            comment = _COMMENT_RE.match(text, i)
            if comments and comment is not None:
                spans.append((comment.start(), comment.end()))
            i = comment.end() if comment is not None else i + 1
            continue
        i += 1
    return spans


def _args(text, start):
    """The argument text of a call whose `(` precedes text[start], strings and nesting aware."""
    depth, i = 1, start
    end = min(len(text), start + _MAX_ARGS)
    while i < end:
        char = text[i]
        if char in "'\"":
            match = _STRING_RE.match(text, i)
            i = match.end() if match is not None else i + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return text[start:end]


def _unquote(literal):
    body = re.sub(r"\A[rRbBuUfF]{0,2}", "", literal)
    for quote in ("'''", '"""', "'", '"'):
        if body.startswith(quote) and body.endswith(quote) and len(body) >= 2 * len(quote):
            return body[len(quote):-len(quote)]
    return body


def _pieces(region, names):
    """The strings of a call's arguments, and the literals its variables name, in source order, so that
    `ROOT + "/tmp"` is joined as `<ROOT>/tmp` and not as `/tmp<ROOT>`."""
    found, at = [], 0
    for match in _STRING_RE.finditer(region):
        found.extend(_variables(region[at:match.start()], names))
        found.append(_unquote(match.group(0)))
        at = match.end()
    found.extend(_variables(region[at:], names))
    return found


def _variables(text, names):
    return [value for name in _NAME_RE.findall(text) for value in names.get(name, ())]


def path_literals(text):
    """The literals found in the arguments of file and process calls (variables resolved one step)."""
    names = {}
    for match in _ASSIGN_RE.finditer(text):
        names.setdefault(match.group(1), []).append(_unquote(match.group(2)))
    found = []
    inert = _inert_spans(text)
    for call in _CALL_RE.finditer(text):
        if any(start <= call.start() < end for start, end in inert):
            continue  # a call written inside a string (test data, a template) is text, not a call
        region = _args(text, call.end())
        literals = [] if call.group(0).rstrip("( \t\n").endswith(_DATA_CALLS) else _pieces(region, names)
        found.extend(literals)
        if len(literals) > 1:
            found.append("".join(literals))  # 'a/' + '.ssh' written as separate pieces
    return found


# -- write targets of inline code (T061, R008 #16) ------------------------------------------
# (module, function) -> [(argument index, op)]; "mode" reads the open mode from the arguments.
_DELETE0, _CREATE0, _REWRITE0 = [(0, "delete")], [(0, "create")], [(0, "rewrite")]
_MOVE, _TO1, _MADE1 = [(0, "delete"), (1, "rewrite")], [(1, "rewrite")], [(1, "create")]
_READ0 = [(0, "read")]  # a read of the same literal makes a later rewrite an edit (read-modify-write)
_WRITERS = {
    "os": {"remove": _DELETE0, "unlink": _DELETE0, "rmdir": _DELETE0, "removedirs": _DELETE0, "mkdir": _CREATE0,
           "makedirs": _CREATE0, "rename": _MOVE, "replace": _MOVE, "renames": _MOVE, "symlink": _MADE1,
           "link": _MADE1, "truncate": _REWRITE0, "open": "flags"},
    "shutil": {"rmtree": _DELETE0, "copy": _TO1, "copy2": _TO1, "copyfile": _TO1, "copytree": _MADE1, "move": _MOVE,
               "unpack_archive": _MADE1},
    "open": {"open": "mode"},
    "fs": {"writeFile": _REWRITE0, "writeFileSync": _REWRITE0, "appendFile": [(0, "edit")],
           "appendFileSync": [(0, "edit")], "createWriteStream": _REWRITE0, "truncate": _REWRITE0,
           "truncateSync": _REWRITE0, "rm": _DELETE0, "rmSync": _DELETE0, "unlink": _DELETE0, "unlinkSync": _DELETE0,
           "rmdir": _DELETE0, "rmdirSync": _DELETE0, "mkdir": _CREATE0, "mkdirSync": _CREATE0, "rename": _MOVE,
           "renameSync": _MOVE, "copyFile": _TO1, "copyFileSync": _TO1, "cp": _TO1, "cpSync": _TO1,
           "symlink": _MADE1, "symlinkSync": _MADE1, "link": _MADE1, "linkSync": _MADE1, "open": "flag1",
           "openSync": "flag1", "readFile": _READ0, "readFileSync": _READ0},
    "File": {"write": _REWRITE0, "binwrite": _REWRITE0, "delete": _DELETE0, "unlink": _DELETE0, "rename": _MOVE,
             "symlink": _MADE1, "link": _MADE1, "open": "flag1", "read": _READ0, "readlines": _READ0},
    "FileUtils": {"rm": _DELETE0, "rm_f": _DELETE0, "rm_r": _DELETE0, "rm_rf": _DELETE0, "remove": _DELETE0,
                  "rmdir": _DELETE0, "remove_dir": _DELETE0, "remove_entry": _DELETE0, "mkdir": _CREATE0,
                  "mkdir_p": _CREATE0, "makedirs": _CREATE0, "touch": _CREATE0, "cp": _TO1, "cp_r": _TO1,
                  "copy": _TO1, "install": _TO1, "mv": _MOVE, "move": _MOVE, "ln": _MADE1, "ln_s": _MADE1,
                  "ln_sf": _MADE1},
}
_MODULES = {"os": "os", "shutil": "shutil", "io": "open", "codecs": "open", "builtins": "open", "gzip": "open",
            "bz2": "open", "lzma": "open", "fs": "fs", "fsp": "fs", "fs.promises": "fs", "File": "File",
            "FileUtils": "FileUtils"}
_NODE_BARE = tuple(n for n in _WRITERS["fs"] if n.endswith("Sync") or n == "createWriteStream")
_WRITE_CALL_RE = re.compile(  # Node's *Sync names are distinctive enough to count after any `.` (`require('fs').x`)
    r"(?:(?<![\w$.])(?:(?P<module>fs\.promises|[A-Za-z_]\w*)\.(?P<attr>[A-Za-z_]\w*)|(?P<bare>open))|"
    r"(?<![\w$])(?P<node>" + "|".join(_NODE_BARE) + r"))\s*\(")
_PATH_CALL_RE = re.compile(r"(?<![\w.])(?:pathlib\.)?(?:Path|PurePath|PosixPath)\s*\(")
_PATH_METHOD_RE = re.compile(r"\)\s*\.\s*(write_text|write_bytes|touch|mkdir|unlink|rmdir|open|rename|replace|"
                             r"symlink_to|hardlink_to|read_text|read_bytes)\s*\(")
_PATH_METHOD_OPS = {"write_text": "rewrite", "write_bytes": "rewrite", "touch": "create", "mkdir": "create",
                    "unlink": "delete", "rmdir": "delete", "symlink_to": "create", "hardlink_to": "create",
                    "read_text": "read", "read_bytes": "read"}
_PERL_OPEN_RE = re.compile(r"(?<![\w$.])open\s*\(?\s*(?:my\s+)?[$\w]+\s*,\s*")
_OS_OPEN_WRITE = re.compile(r"\bO_(?:WRONLY|RDWR|CREAT|TRUNC|APPEND)\b")


def _split_args(region):
    """The top-level comma-separated arguments of a call's argument text (strings and nesting aware)."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(region):
        char = region[i]
        if char in "'\"":
            match = _STRING_RE.match(region, i)
            i = match.end() if match is not None else i + 1
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(region[start:i].strip())
            start = i + 1
        i += 1
    tail = region[start:].strip()
    if tail or parts:
        parts.append(tail)
    return parts


def _values(arg, names):
    """The literal values an argument can have: a plain (not f-) string, or a name bound to literals; [] when
    the audit cannot know it (a concatenation, a call, an f-string)."""
    arg = arg.strip()
    if _STRING_RE.fullmatch(arg) is not None:
        prefix = _PREFIX_RE.match(arg).group(0).lower()
        return [] if "f" in prefix else [_unquote(arg)]
    if _NAME_RE.fullmatch(arg) is not None:
        return list(names.get(arg, ()))
    return []


def _positional_and_keywords(args):
    positional, keywords = [], {}
    for arg in args:
        match = re.match(r"([A-Za-z_]\w*)\s*=(?!=)\s*(.*)\Z", arg, re.DOTALL)
        if match is not None:
            keywords[match.group(1)] = match.group(2)
        else:
            positional.append(arg)
    return positional, keywords


def _mode_op(mode):
    if any(c in mode for c in "wx"):
        return "rewrite"
    if any(c in mode for c in "a+"):
        return "edit"
    return None


def _call_ops(table, args, names):
    positional, keywords = _positional_and_keywords(args)
    if table == "mode":  # open(path, mode='r')
        path = positional[0] if positional else keywords.get("file", "")
        mode = positional[1] if len(positional) > 1 else keywords.get("mode", "'r'")
        ops = {_mode_op(m) or "read" for m in _values(mode, names)} or {None}
        return [(path, op) for op in ops if op is not None]
    if table == "flags":  # os.open(path, os.O_WRONLY | os.O_CREAT)
        flags = positional[1] if len(positional) > 1 else keywords.get("flags", "")
        if _OS_OPEN_WRITE.search(flags) is None:
            return []
        return [(positional[0] if positional else keywords.get("path", ""),
                 "edit" if "O_APPEND" in flags and "O_TRUNC" not in flags else "rewrite")]
    if table == "flag1":  # fs.openSync(path, 'w'), File.open(path, 'w')
        mode = positional[1] if len(positional) > 1 else "'r'"
        ops = {_mode_op(m) for m in _values(mode, names)}
        return [(positional[0], op) for op in ops if op is not None] if positional else []
    return [(positional[index], op) for index, op in table if index < len(positional)]


def write_literals(text):
    """[(path, op)] of the literal paths inline code writes or deletes (T061, R008 #16): a write-mode `open`, the
    `os`/`shutil` writers (`remove`, `unlink`, `rename`, `replace`, `rmtree`, `copy*`, `move`, `makedirs`, ...),
    `Path(...).write_text/write_bytes/unlink/...`, Node's `fs` writers, Ruby's `File`/`FileUtils` and Perl's
    `open(FH, '>', ...)`. Only a plain string, or a name bound to one (`p = 'x'`), is a path; anything computed is
    left out (it cannot be named). A call written inside a string literal or a comment is text, not a call."""
    names = {}
    for match in _ASSIGN_RE.finditer(text):
        names.setdefault(match.group(1), []).append(_unquote(match.group(2)))
    inert = _inert_spans(text, comments=True)
    is_text = lambda at: any(start <= at < end for start, end in inert)  # noqa: E731
    found = []
    for call in _WRITE_CALL_RE.finditer(text):
        if is_text(call.start()):
            continue
        module = _MODULES.get(call.group("module")) if call.group("module") else (
            "open" if call.group("bare") else "fs")
        table = _WRITERS.get(module, {}).get(call.group("attr") or call.group("bare") or call.group("node"))
        if table is None:
            continue
        for arg, op in _call_ops(table, _split_args(_args(text, call.end())), names):
            found.extend((value, op) for value in _values(arg, names))
    for call in _PATH_CALL_RE.finditer(text):
        if is_text(call.start()):
            continue
        region = _args(text, call.end())
        method = _PATH_METHOD_RE.match(text, call.end() + len(region))
        pieces = [_values(arg, names) for arg in _split_args(region)]
        if method is None or not pieces or any(len(p) != 1 for p in pieces):
            continue
        path = "/".join(p[0] for p in pieces)
        name = method.group(1)
        margs = _split_args(_args(text, method.end()))
        if name == "open":
            positional, keywords = _positional_and_keywords(margs)
            mode = positional[0] if positional else keywords.get("mode", "'r'")
            found.extend((path, _mode_op(m) or "read") for m in set(_values(mode, names)))
        elif name in ("rename", "replace"):
            found.append((path, "delete"))
            found.extend((value, "rewrite") for value in (_values(margs[0], names) if margs else []))
        else:
            found.append((path, _PATH_METHOD_OPS[name]))
    for call in _PERL_OPEN_RE.finditer(text):
        if is_text(call.start()):
            continue
        rest = _split_args(_args(text, call.end()) if text[call.start():call.end()].count("(") else
                           text[call.end():call.end() + 400].split(";", 1)[0])
        if len(rest) >= 2:
            if any(">" in m or "+<" in m for m in _values(rest[0], names)):
                found.extend((value, "rewrite") for value in _values(rest[1], names))
        elif rest:
            for value in _values(rest[0], names):
                if value.startswith((">", "+<")):
                    found.append((value.lstrip(">+<").strip(), "edit" if value.startswith(">>") else "rewrite"))
    reads = {value for value, op in found if op == "read"}
    return [(value, "edit" if op == "rewrite" and value in reads else op) for value, op in found if op != "read"]


# -- concatenations folded before the scan (T062) -------------------------------------------
_SIMPLE_RE = re.compile(r"(?:[rRbBuU]{1,2})?(?:'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\")")  # one line, not an f-string
_ELEM_RE = re.compile(r"(?:" + _SIMPLE_RE.pattern + r")|\$?(?P<name>[A-Za-z_]\w*)(?![\w(\[.]|\s*\()")
_PLUS_RE = re.compile(r"[ \t]*\+(?!=)\s*|\s+\+(?!=)\s*")
_DOT_RE = re.compile(r"[ \t]+\.[ \t]+")      # Perl's `.` between strings (`'a' . 'b'`), spaced
_ADJ_RE = re.compile(r"[ \t]+(?=[rRbBuU]{0,2}['\"])")  # Python's implicit concatenation (`'a' 'b'`)
_JOIN_RE = re.compile(r"(?<![\w.])(?:os\.path|posixpath)\.join\s*\(")
_PATH_DIV_RE = re.compile(r"(?<![\w.])((?:pathlib\.)?(?:Path|PurePath|PosixPath))\s*\(\s*(" + _SIMPLE_RE.pattern +
                          r")\s*\)((?:\s*/\s*(?:" + _SIMPLE_RE.pattern + r"))+)")
_MAX_ROUNDS = 4


def _quoted(body):
    if '"' not in body:
        return '"' + body + '"'
    return "'" + body.replace("'", "\\'") + "'"


def _elem_value(match, names):
    if match.group("name") is None:
        return _unquote(match.group(0))
    values = names.get(match.group("name"), ())
    return values[0] if len(set(values)) == 1 else None


def _fold_chains(text, names):
    """One pass: `'a' + 'b'`, `x + 'b'` (x bound to one literal), Perl's `'a' . 'b'` and Python's `'a' 'b'` become one
    literal. Strings and `#` comments are skipped whole, so a chain never starts inside one."""
    out, i, n = [], 0, len(text)
    while i < n:
        char = text[i]
        if char == "#" and (i == 0 or text[i - 1].isspace()):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(text[i:end])
            i = end
            continue
        prev = text[i - 1] if i else " "
        string = _STRING_RE.match(text, i) if char in "'\"rRbBuUfF" else None
        if string is not None and (_SIMPLE_RE.fullmatch(string.group(0)) is None or prev.isalnum() or prev == "_"):
            out.append(string.group(0))  # a triple-quoted or f-string, or one glued to a name: skipped whole
            i = string.end()
            continue
        first = _ELEM_RE.match(text, i) if not (prev.isalnum() or prev in "_.$") else None
        if first is None:
            string = _STRING_RE.match(text, i) if char in "'\"" else None
            step = string.end() if string is not None else i + 1
            out.append(text[i:step])
            i = step
            continue
        values, end, strings = [_elem_value(first, names)], first.end(), first.group("name") is None
        while True:
            op = _PLUS_RE.match(text, end)
            dot_or_adj = _DOT_RE.match(text, end) or _ADJ_RE.match(text, end)
            nxt = _ELEM_RE.match(text, op.end()) if op is not None else None
            if nxt is None and dot_or_adj is not None and values[-1] is not None:
                nxt = _SIMPLE_RE.match(text, dot_or_adj.end())
                nxt = _ELEM_RE.match(text, dot_or_adj.end()) if nxt is not None else None
            if nxt is None:
                break
            values.append(_elem_value(nxt, names))
            strings = strings or nxt.group("name") is None
            end = nxt.end()
        if len(values) > 1 and strings and all(v is not None for v in values):
            out.append(_quoted("".join(values)))
        else:
            out.append(text[i:end])
        i = end
    return "".join(out)


def _fold_joins(text):
    """`os.path.join('a', 'b')` of literals only is `'a/b'`; `Path('a') / 'b'` is `Path('a/b')`."""
    def join(match):
        region = _args(text, match.end())
        args = _split_args(region)
        if not args or any(_SIMPLE_RE.fullmatch(a) is None for a in args):
            return None
        path = ""
        for arg in args:
            piece = _unquote(arg)
            path = piece if piece.startswith("/") or not path else path.rstrip("/") + "/" + piece
        return match.start(), match.end() + len(region) + 1, _quoted(path)
    edits = [e for e in (join(m) for m in _JOIN_RE.finditer(text)) if e is not None]
    for start, end, literal in reversed(edits):
        if text[end - 1:end] == ")":
            text = text[:start] + literal + text[end:]
    def divide(match):
        pieces = [_unquote(match.group(2))] + [_unquote(p) for p in re.findall(_SIMPLE_RE.pattern, match.group(3))]
        return match.group(1) + "(" + _quoted("/".join(p.strip("/") if k else p.rstrip("/")
                                                        for k, p in enumerate(pieces))) + ")"
    return _PATH_DIV_RE.sub(divide, text)


def fold_concat(text):
    """`text` with literal concatenations folded into one literal, so that a path split into pieces
    (`'/var/tmp/.co' + 'nfig/x'`, `p = base + 'x'`, `os.path.join('/var/tmp', '.config')`, `Path('/a') / 'b'`) is
    scanned whole (T062). A name counts when it is bound to exactly one literal (`name = 'literal'`); a few rounds
    resolve chains of such names."""
    for _ in range(_MAX_ROUNDS):
        names = {}
        for match in _ASSIGN_RE.finditer(text):
            names.setdefault(match.group(1), []).append(_unquote(match.group(2)))
        folded = _fold_joins(_fold_chains(text, names))
        if folded == text:
            break
        text = folded
    return text
