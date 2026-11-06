"""A small, conservative shell lexer for `rigor trajectory`.

It does not run anything. It splits a command string into simple commands (words with quotes
removed, redirections, here-documents, leading assignments, command substitutions) so the audit can
look at what a Bash tool call would do. Text it cannot interpret becomes an unresolved marker, never
a silent gap.
"""

import re

DOLLAR = "\x01"      # a `$` that is literal (single quotes, backslash)
UNRESOLVED = "\x02"  # a command substitution or other value the lexer cannot know

_REDIR_RE = re.compile(r"<<<|<<-|<<|<&|<>|<|&>>|&>|>>|>&|>\||>")
_OPERATORS = ";&|()\n"
_WORD_END = " \t" + _OPERATORS + "<>"
_LEADING = ("do", "then", "else", "elif", "if", "{")  # reserved words that only start a command
_ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f",
         "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


class Word:
    __slots__ = ("text", "subs", "quoted")

    def __init__(self, text, subs, quoted):
        self.text = text      # quotes removed; live expansions still written as $NAME / ${NAME}
        self.subs = subs      # texts of $(...), `...`, <(...) found inside
        self.quoted = quoted  # any quoting was used


class Redirect:
    __slots__ = ("op", "fd", "target")

    def __init__(self, op, fd, target):
        self.op = op
        self.fd = fd
        self.target = target


class Heredoc:
    __slots__ = ("delimiter", "body", "strip_tabs", "quoted")

    def __init__(self, delimiter, strip_tabs, quoted):
        self.delimiter = delimiter
        self.strip_tabs = strip_tabs
        self.quoted = quoted
        self.body = ""


class Command:
    __slots__ = ("words", "assigns", "redirects", "heredocs", "group", "raw")

    def __init__(self, group):
        self.words = []
        self.assigns = []    # (name, Word) before the command name
        self.redirects = []
        self.heredocs = []
        self.group = group   # commands joined by `|` share a group
        self.raw = ""

    def empty(self):
        return not (self.words or self.assigns or self.redirects or self.heredocs)


def ansi_decode(body):
    out = []
    i = 0
    while i < len(body):
        char = body[i]
        if char != "\\" or i + 1 >= len(body):
            out.append(char)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in _ANSI:
            out.append(_ANSI[nxt])
            i += 2
            continue
        match = re.match(r"x([0-9A-Fa-f]{1,2})|([0-7]{1,3})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})",
                         body[i + 1:])
        if match is None:
            out.append(nxt)
            i += 2
            continue
        digits = match.group(1) or match.group(3) or match.group(4)
        code = int(digits, 16) if digits else int(match.group(2), 8)
        out.append(chr(min(code, 0x10FFFF)))
        i += 1 + match.end()
    return "".join(out).replace("$", DOLLAR)


def _balanced(text, start, opener, closer):
    """Index just past the closer matching the opener that ends at text[start-1]."""
    depth = 1
    i = start
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char in "'\"":
            end = text.find(char, i + 1)
            i = len(text) if end < 0 else end + 1
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def arith_end(text, i):
    """Index past `$((...))` starting at text[i], or -1 when text[i:] is not an arithmetic expansion."""
    if not text.startswith("$((", i):
        return -1
    end = _balanced(text, i + 2, "(", ")")
    return end if text[end - 2:end] == "))" else -1


def nested_subs(body):
    """Texts of the `$(...)` and backtick substitutions written inside an arithmetic expression."""
    found, i = [], 0
    while i < len(body):
        if body.startswith("$(", i):
            end = _balanced(body, i + 2, "(", ")")
            found.append(body[i + 2:end - 1])
            i = end
        elif body[i] == "`":
            end = body.find("`", i + 1)
            end = len(body) if end < 0 else end
            found.append(body[i + 1:end])
            i = end + 1
        else:
            i += 1
    return found


class Lexer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.commands = []
        self.cur = Command(0)
        self.group = 0
        self.pending = []
        self.last_end = -1

    # -- words -------------------------------------------------------------------------------
    def read_word(self):
        text, i = self.text, self.pos
        out, subs, quoted = [], [], False
        while i < len(text) and text[i] not in _WORD_END:
            char = text[i]
            if char == "\\":
                i, quoted = self._escape(i, out, quoted)
            elif char == "'":
                end = text.find("'", i + 1)
                end = len(text) if end < 0 else end
                out.append(text[i + 1:end].replace("$", DOLLAR))
                i, quoted = end + 1, True
            elif char == '"':
                i = self._double(i, out, subs)
                quoted = True
            elif char == "$" and text.startswith("$'", i):
                end = self._ansi_end(i + 2)
                out.append(ansi_decode(text[i + 2:end]))
                i, quoted = end + 1, True
            elif char == "$" and arith_end(text, i) > 0:
                end = arith_end(text, i)
                subs.extend(nested_subs(text[i + 3:end - 2]))
                out.append(UNRESOLVED)
                i = end
            elif char == "$" and text.startswith("$(", i):
                end = _balanced(text, i + 2, "(", ")")
                subs.append(text[i + 2:end - 1])
                out.append(UNRESOLVED)
                i = end
            elif char == "$" and text.startswith("${", i):
                end = _balanced(text, i + 2, "{", "}")
                out.append(text[i:end])
                i = end
            elif char == "`":
                end = text.find("`", i + 1)
                end = len(text) if end < 0 else end
                subs.append(text[i + 1:end])
                out.append(UNRESOLVED)
                i = end + 1
            else:
                out.append(char)
                i += 1
        self.pos = i
        return Word("".join(out), subs, quoted)

    def _escape(self, i, out, quoted):
        text = self.text
        if i + 1 >= len(text):
            out.append("\\")
            return i + 1, quoted
        nxt = text[i + 1]
        if nxt != "\n":
            out.append(DOLLAR if nxt == "$" else nxt)
        return i + 2, True

    def _ansi_end(self, start):
        i = start
        while i < len(self.text) and self.text[i] != "'":
            i += 2 if self.text[i] == "\\" else 1
        return min(i, len(self.text))

    def _double(self, i, out, subs):
        text = self.text
        i += 1
        while i < len(text) and text[i] != '"':
            char = text[i]
            if char == "\\" and i + 1 < len(text):
                nxt = text[i + 1]
                if nxt in '$"\\`':
                    out.append(DOLLAR if nxt == "$" else nxt)
                elif nxt != "\n":
                    out.append("\\" + nxt)
                i += 2
            elif char == "$" and arith_end(text, i) > 0:
                end = arith_end(text, i)
                subs.extend(nested_subs(text[i + 3:end - 2]))
                out.append(UNRESOLVED)
                i = end
            elif char == "$" and text.startswith("$(", i):
                end = _balanced(text, i + 2, "(", ")")
                subs.append(text[i + 2:end - 1])
                out.append(UNRESOLVED)
                i = end
            elif char == "$" and text.startswith("${", i):
                end = _balanced(text, i + 2, "{", "}")
                out.append(text[i:end])
                i = end
            elif char == "`":
                end = text.find("`", i + 1)
                end = len(text) if end < 0 else end
                subs.append(text[i + 1:end])
                out.append(UNRESOLVED)
                i = end + 1
            else:
                out.append(char)
                i += 1
        return i + 1

    # -- structure ---------------------------------------------------------------------------
    def end_command(self, new_group=True):
        if not self.cur.empty():
            self.cur.raw = self.cur.raw.strip()
            self.commands.append(self.cur)
        self.cur = Command(self.group if not new_group else self.group + 1)
        if new_group:
            self.group += 1

    def _read_heredocs(self):
        lines = self.text[self.pos:].split("\n")
        used = 0
        for doc in self.pending:
            body = []
            while used < len(lines):
                line = lines[used]
                used += 1
                if (line.lstrip("\t") if doc.strip_tabs else line) == doc.delimiter:
                    break
                body.append(line)
            doc.body = "\n".join(body)
        self.pos += sum(len(line) + 1 for line in lines[:used])
        self.pending = []

    def _redirect(self):
        match = _REDIR_RE.match(self.text, self.pos)
        op = match.group(0)
        start = self.pos
        fd = None
        words = self.cur.words
        if words and self.last_end == start and re.fullmatch(r"\d+", words[-1].text) and not words[-1].quoted:
            fd = words.pop().text
        self.pos = match.end()
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1
        if self.text.startswith(("(",), self.pos) and op in ("<", ">"):
            end = _balanced(self.text, self.pos + 1, "(", ")")
            target = Word(UNRESOLVED, [self.text[self.pos + 1:end - 1]], False)
            self.pos = end
        else:
            target = self.read_word()
        self.cur.raw += " " + self.text[start:self.pos]
        if op in ("<<", "<<-"):
            doc = Heredoc(target.text, op == "<<-", target.quoted)
            self.cur.heredocs.append(doc)
            self.pending.append(doc)
        else:
            self.cur.redirects.append(Redirect(op, fd, target))

    def _operator(self):
        text, i = self.text, self.pos
        char = text[i]
        two = text[i:i + 2]
        if char == "\n":
            self.pos += 1
            if self.pending:
                self._read_heredocs()
            self.end_command()
        elif two in ("&&", "||", ";;", ";&"):
            self.pos += 2
            self.end_command()
        elif two == "|&" or char == "|":
            self.pos += len(two) if two == "|&" else 1
            self.end_command(new_group=False)
        else:
            self.pos += 1
            self.end_command()

    def run(self):
        text = self.text
        while self.pos < len(text):
            char = text[self.pos]
            if char in " \t":
                self.pos += 1
            elif char == "#" and (self.pos == 0 or text[self.pos - 1] in " \t\n;&|("):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end < 0 else end
            elif char == "\\" and text.startswith("\\\n", self.pos):
                self.pos += 2
            elif char == "&" and text.startswith("&>", self.pos):
                self._redirect()
            elif char in _OPERATORS:
                self._operator()
            elif char in "<>":
                self._redirect()
            else:
                start = self.pos
                word = self.read_word()
                self.last_end = self.pos
                self._add_word(word, text[start:self.pos])
        self.end_command()
        return self.commands

    def _add_word(self, word, raw):
        cur = self.cur
        cur.raw += " " + raw
        if not (cur.words or cur.assigns) and not word.quoted and not word.subs and word.text in _LEADING:
            return  # `do x=1`, `then cmd`, `{ cmd`: the reserved word is not the command
        match = None if cur.words else re.match(r"[A-Za-z_][A-Za-z0-9_]*=", raw)
        if match is not None:
            name, value = word.text.split("=", 1)
            cur.assigns.append((name, Word(value, word.subs, word.quoted)))
        else:
            cur.words.append(word)


def parse(text):
    """The simple commands of `text` in order. Never raises on odd input."""
    return Lexer(text).run()
