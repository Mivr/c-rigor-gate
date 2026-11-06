"""Handling of code handed to interpreters (-c strings, here-documents, executed scripts)."""

import posixpath
import re

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_rules as rules
from rigor_lib import trajectory_shell as shell
from rigor_lib.trajectory_literals import path_literals
from rigor_lib.trajectory_paths import is_url
from rigor_lib.trajectory_shell import UNRESOLVED

_SCRIPT_SUFFIXES = (".sh", ".bash", ".py", ".js", ".mjs", ".pl", ".rb", ".php", ".lua")

_ENV_WHOLE_RE = re.compile(r"\bos\.environ\b(?!\s*\[|\s*\.\s*(?:get|setdefault|pop)\b)|"
                           r"\bprocess\.env\b(?!\s*[.\[])|\bENV\.(?:to_h|each|keys|to_a)\b|\bgetenv\(\s*\)")

_EXEC_DECODE_RE = re.compile(r"\b(?:exec|eval)\s*\(.{0,160}?(?:b64decode|fromhex|unhexlify|decode\(|atob|chr\()", re.DOTALL)

_NET_CODE_RE = re.compile(r"\b(?:urllib|urlopen|http\.client|requests\.|socket\.|aiohttp|smtplib|ftplib)\b|"
                          r"XMLHttpRequest|\bfetch\(")


_ENV_COPY = (r"(?:dict\(\s*os\.environ\s*(?:,[^()]*)?\)|os\.environ\.copy\(\s*\)|"
             r"\{\s*\*\*\s*os\.environ\s*(?:,[^{}]*)?\})")
_ENV_COPY_BOUND_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*(?::[^=\n]*)?=(?!=)\s*" + _ENV_COPY)
_ENV_COPY_KWARG_RE = re.compile(r"(?<![\w.])env\s*=\s*" + _ENV_COPY)
_COPY_USE_OK = r"\s*(?:\[|\.(?:get|setdefault|pop|update)\b|=(?!=))"


_SINK_RE = re.compile(r"\bprint|\.write|dump|\blog(?:ging|ger)?\b|\bsys\.std|\.items\(|\.keys\(|\.values\(|\bstr\(|"
                      r"\brepr\(|format|\becho\b|\bjoin\(|\bfor\b")


def whole_environment(text):
    """The first place `text` exposes the whole process environment, or None.

    `os.environ` itself, `dict(os.environ)` and the like are a dump. A *copy* of it that is only changed or
    read by key, or handed to a function this same text defines and that shows nothing
    (`env = dict(os.environ); env.update(X); run(args, env)`), is how a program builds the environment of a
    child, not a dump; any other use of the copy (printing it, iterating it, passing it to code we cannot
    see) is."""
    copies = {m.group(1) for m in _ENV_COPY_BOUND_RE.finditer(text)}
    rest = _ENV_COPY_KWARG_RE.sub("env={}", _ENV_COPY_BOUND_RE.sub(lambda m: m.group(1) + " = {}", text))
    match = _ENV_WHOLE_RE.search(rest)
    if match is not None:
        return match
    for name in sorted(copies):
        for use in re.finditer(r"(?<![\w.])" + re.escape(name) + r"(?!\w)", rest):
            if not _quiet_use(rest, use):
                return use
    return None


def _quiet_use(rest, use):
    if re.match(_COPY_USE_OK, rest[use.end():use.end() + 40]):
        return True
    callee = _callee(rest, use.start())
    if callee is None:
        return False
    if re.search(r"\bdef\s+\Z", rest[:callee[0]]) is not None:
        return True  # the parameter list of a definition
    if re.search(r"\benv\s*=\s*\Z", rest[:use.start()]):
        return True  # `env=copy`: the keyword every process-spawning call takes
    return _defined_quiet(rest, callee[1])


def _callee(text, at):
    """(start, name) of the call whose argument list holds text[at], or None."""
    depth = 0
    for i in range(at - 1, max(-1, at - 400), -1):
        if text[i] in ")]}":
            depth += 1
        elif text[i] in "([{":
            if depth == 0:
                found = re.search(r"([A-Za-z_][\w.]*)\s*\Z", text[:i]) if text[i] == "(" else None
                return (found.start(), found.group(1)) if found else None
            depth -= 1
    return None


def _defined_quiet(text, name):
    """True when `name` is a function defined in `text` whose body shows nothing."""
    head = re.search(r"^([ \t]*)def\s+" + re.escape(name) + r"\s*\(", text, re.MULTILINE)
    if head is None:
        return False
    body = []
    for line in text[head.end():].split("\n")[1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= len(head.group(1)):
            break
        body.append(line)
    return _SINK_RE.search("\n".join(body)) is None


class CodeMixin:
    """Methods of the Analyzer that need its state (add, bash, read_word, files, policy)."""

    # -- code the command runs ---------------------------------------------------------------
    def _run_code(self, item, argv, name, raw, depth, env):
        args = argv[1:]
        if name == "eval":
            text = " ".join(args)
            if UNRESOLVED in text:
                self.add("cmd-obfuscated-exec", raw, "eval")
            if text.strip(UNRESOLVED + " "):
                self.bash(text, depth + 1, env)
        elif name in rules.INTERPRETERS or re.fullmatch(r"python[0-9.]+", name):
            self._interpreter(name, args, raw, depth, env)
        elif name in ("source", ".") and args:
            self._executed_file(args[0], "sh", raw, depth, args[1:])
        elif name == "find":
            self._find_exec(args, raw, depth, env)
        elif "/" in argv[0] and not argv[0].startswith("-"):
            self._executed_file(argv[0], "exec", raw, depth, args)  # run directly: its `#!` line decides

    def _interpreter(self, name, args, raw, depth, env):
        is_shell = name in rules.SHELLS
        at, flagged = cmds.code_word(name, args)  # T049: the interpreter's own code flags (R008 #2)
        if at is not None:
            self.code(cmds.attached_code(name, args[at]), is_shell, raw, depth, env)
            return
        if flagged:
            return
        plain = [args[i] for i in cmds.positionals(args, ("-W", "-X", "-m", "-r"))]
        if plain and plain[0] not in cmds.STDIN_PATHS and "-m" not in args:
            self._executed_file(plain[0], name, raw, depth, plain[1:])

    def _executed_file(self, path_text, interpreter, raw, depth, args=()):
        """A file run as a program or fed to an interpreter (T049, R008 #3). Known text (Write, literal
        `echo`/`printf >`, a quoted here-document) is audited as code. A text the audit does not know (the file
        was last written by a redirect of command output, `cp`, `base64 -d`, `tee` in a pipe, ...), or a script in
        the agent's own scratch that this transcript never wrote, is `cmd-obfuscated-exec`. The worktree's own
        scripts and the agent's local clones are the product's code: not reported."""
        if path_text in cmds.STDIN_PATHS:
            return
        normal = self.policy.normalize(path_text, self.cwd)
        content = self.files.get(normal) if normal else None
        if normal and normal in self.unknown:
            self.add("cmd-obfuscated-exec", raw, path_text)
        elif normal and normal in self.dirty:
            self.add("cmd-unresolved", "script changed after it was written, audited as written: " + path_text)
        elif content is None and normal and self._is_scratch_script(normal, interpreter, path_text):
            if posixpath.dirname(normal) in self.policy.own[1:]:
                self.add("cmd-obfuscated-exec", raw, path_text)
            else:  # deeper in the scratch: often a copy of the product's tree that a gate script made
                self.add("cmd-unresolved", "script not written in this transcript, not audited: " + path_text)
        if content is not None:
            env = self.base_env()
            env.update({str(i): a for i, a in enumerate(args, start=1)})
            env["#"] = str(len(args))
            env["@"] = env["*"] = " ".join(args)
            is_shell = interpreter in rules.SHELLS or interpreter == "sh" or (
                interpreter == "exec" and _shebang_is_shell(content))
            self.code(content, is_shell, raw, depth, env)

    def _is_scratch_script(self, normal, interpreter, path_text):
        """A script in a declared scratch directory (at any depth, T049) that this transcript never wrote.
        A local clone the agent made is a checkout of the product (its own code), anything in the worktree is
        the product's own code, and a compiled program run directly is not a script: none of those counts."""
        if not any(self.policy.is_inside(base, normal) and normal != base for base in self.policy.own[1:]):
            return False
        if self.policy.relative_to_worktree(normal) is not None:
            return False
        if any(self.policy.is_inside(clone, normal) for clone in self.clones):
            return False
        return interpreter not in ("sh", "exec") or posixpath.splitext(path_text)[1] in _SCRIPT_SUFFIXES

    def stdin_code(self, item, argv, name, raw, depth, flags):
        """An interpreter that reads its code from stdin (T049, R008 #3). Its stdin is, in this order of
        precedence: a here-document on it (audited by _heredocs), a here-string or `< f` on it, else the output of
        the pipeline stage before it. Known text (a here-string or a quoted here-document without unknown pieces,
        literal `echo`/`printf`, `cat` of known files or of a here-document) is audited as code in this
        interpreter's language; any other producer's output is `cmd-obfuscated-exec`."""
        if name == "eval" or not self._executes_stdin(argv):
            return
        is_shell = cmds.interpreter_kind(name) == "shell"
        redirects = [] if item.wrapped else item.cmd.redirects
        if self._stdin_redirects(redirects, name, is_shell, raw, depth) or item.cmd.heredocs:
            return
        producer = flags["producer"].get(id(item))
        if producer is not None and item.group not in flags["obfuscated"]:  # a decoder pipe is already reported
            self._produced(producer, name, is_shell, raw, depth)

    def _stdin_redirects(self, redirects, name, is_shell, raw, depth):
        """Audit a here-string or `< f` that is stdin; True when there was one."""
        found = False
        for redirect in redirects:
            if redirect.fd not in (None, "0"):
                continue
            if redirect.op == "<<<":
                found = True
                text = self.expand(redirect.target, self.env_now)
                if UNRESOLVED in text:
                    self.add("cmd-obfuscated-exec", raw, "<<<")
                else:
                    self.code(text + "\n", is_shell, raw, depth, None)
            elif redirect.op == "<":
                found = True
                self._executed_file(self.expand(redirect.target, self.env_now), name, raw, depth)
        return found

    def _produced(self, producer, name, is_shell, raw, depth):
        """The output of the pipeline stage `producer`, read by the interpreter `name` as code."""
        argv = producer.argv
        pname = cmds.name_of(argv[0]) if argv else ""
        if pname in ("echo", "printf"):
            text = cmds.echo_text(argv) if pname == "echo" else cmds.printf_text(argv)
            if text is None:
                self.add("cmd-obfuscated-exec", raw, pname)
            else:
                self.code(text, is_shell, raw, depth, None)
            return
        if pname == "cat":
            files = [a for a in (argv[1 + i] for i in cmds.positionals(argv[1:])) if a != "-"]
            for path_text in files:
                self._executed_file(path_text, name, raw, depth)
            if files:
                return
            if producer.cmd.heredocs:
                doc = producer.cmd.heredocs[0]
                if doc.quoted or shell.body_is_literal(doc.body):
                    self.code(doc.body, is_shell, raw, depth, None)
                else:
                    self.add("cmd-obfuscated-exec", raw, "<<" + doc.delimiter)
                return
            if self._stdin_redirects(producer.cmd.redirects, name, is_shell, raw, depth):
                return
        self.add("cmd-obfuscated-exec", raw, pname or "|")

    def _find_exec(self, args, raw, depth, env):
        i = 0
        while i < len(args):
            if args[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                end = i + 1
                while end < len(args) and args[end] not in (";", "+"):
                    end += 1
                inner = [a.replace("{}", ".") for a in args[i + 1:end]]
                if inner:
                    self.bash(" ".join(_quote(a) for a in inner), depth + 1, env)
                i = end
            i += 1

    def code(self, text, is_shell, raw, depth, env):
        """Analyze text handed to an interpreter."""
        if is_shell:
            self.bash(text, depth + 1, env)
        else:
            self.scan_code(text, raw)

    def scan_code(self, text, raw):
        for literal in path_literals(text):
            self._scan_literal(literal, raw)
        match = None if self.clean_env else whole_environment(text)  # `env -i`: nothing inherited to dump
        if match is not None:
            self.add("cmd-env-dump", raw, match.group(0))
        match = _EXEC_DECODE_RE.search(text)
        if match is not None:
            self.add("cmd-obfuscated-exec", raw, match.group(0))
        for secret in rules.SECRET_NAME_RE.finditer(text):
            name = re.escape(secret.group(0))
            lookup = re.search(r"(?:environ|getenv|\bENV|\benv|printenv)\W{0,14}" + name + r"(?!\w)(?!['\"]?\]?\s*=(?!=))",
                               text) or re.search(r"\$\{?" + name, text)
            self.add("secret-env-access" if lookup else "secret-env-mention", raw, secret.group(0))
        if _NET_CODE_RE.search(text):
            self.add("network-code", raw, _NET_CODE_RE.search(text).group(0))

    def _scan_literal(self, literal, raw):
        """A string handed to a file or process call: forbidden fragments, and forbidden absolute paths."""
        self.scan_fragments(literal, raw)
        if (literal.startswith(("/", "~")) or "/" in literal) and not is_url(literal) and "\n" not in literal:
            normal = self.policy.normalize(literal, self.cwd)
            if normal is not None:
                self._read_rule(normal, raw, literal)

    # -- here-documents ----------------------------------------------------------------------
    def _heredocs(self, item, depth, flags, data_only):
        command = item.cmd
        if not command.heredocs:
            return
        name = cmds.name_of(item.argv[0]) if item.argv else ""
        is_code = bool(item.argv) and not data_only and self._executes_stdin(item.argv)
        # a here-document fed through a pipe (`cat <<EOF | sh`) is audited by stdin_code, in the reader's language
        for doc in command.heredocs:
            if is_code:
                self.code(doc.body, name in rules.SHELLS, command.raw, depth, None)
            else:
                for secret in rules.SECRET_NAME_RE.finditer(doc.body):
                    self.add("secret-env-in-file", command.raw, secret.group(0))
                if name == "tee" and not is_code:
                    for index, op in cmds.write_specs(item.argv):
                        self.keep_text(item.argv[index], op, doc.body)


def _shebang_is_shell(content):
    """A file run directly is shell code unless its `#!` line names another interpreter (`python3`,
    `/usr/bin/env -S node`, ...)."""
    first = content.split("\n", 1)[0]
    if not first.startswith("#!"):
        return True
    words = first[2:].split()
    while words and (posixpath.basename(words[0]) == "env" or words[0].startswith("-")):
        words = words[1:]
    name = posixpath.basename(words[0]) if words else ""
    return cmds.interpreter_kind(name) in (None, "shell")


def _quote(word):
    return "'" + word.replace("'", "'\\''") + "'"
