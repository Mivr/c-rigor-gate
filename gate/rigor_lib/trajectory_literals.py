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


def path_literals(text):
    """The literals found in the arguments of file and process calls (variables resolved one step)."""
    names = {}
    for match in _ASSIGN_RE.finditer(text):
        names.setdefault(match.group(1), []).append(_unquote(match.group(2)))
    found = []
    for call in _CALL_RE.finditer(text):
        region = _args(text, call.end())
        literals = [_unquote(m.group(0)) for m in _STRING_RE.finditer(region)]
        for name in _NAME_RE.findall(_STRING_RE.sub(" ", region)):
            literals.extend(names.get(name, ()))
        found.extend(literals)
        if len(literals) > 1:
            found.append("".join(literals))  # 'a/' + '.ssh' written as separate pieces
    return found
