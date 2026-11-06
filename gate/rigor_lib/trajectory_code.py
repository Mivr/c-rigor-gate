"""Handling of code handed to interpreters (-c strings, here-documents, executed scripts)."""

import re

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import UNRESOLVED

_ENV_WHOLE_RE = re.compile(r"\bos\.environ\b(?!\s*\[|\s*\.\s*(?:get|setdefault|pop)\b)|"
                           r"\bprocess\.env\b(?!\s*[.\[])|\bENV\.(?:to_h|each|keys|to_a)\b|\bgetenv\(\s*\)")

_EXEC_DECODE_RE = re.compile(r"\b(?:exec|eval)\s*\(.{0,160}?(?:b64decode|fromhex|unhexlify|decode\(|atob|chr\()", re.DOTALL)

_NET_CODE_RE = re.compile(r"\b(?:urllib|urlopen|http\.client|requests\.|socket\.|aiohttp|smtplib|ftplib)\b|"
                          r"XMLHttpRequest|\bfetch\(")


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
            self._executed_file(args[0], "sh", raw, depth)
        elif name == "find":
            self._find_exec(args, raw, depth, env)
        elif "/" in argv[0] and not argv[0].startswith("-"):
            self._executed_file(argv[0], "sh", raw, depth)

    def _interpreter(self, name, args, raw, depth, env):
        is_shell = name in rules.SHELLS
        code_flag = next((i for i, a in enumerate(args) if a in ("-c", "-e", "-E") or
                          re.fullmatch(r"-[a-zA-Z]*[ce]", a)), None)
        if code_flag is not None and code_flag + 1 < len(args):
            self.code(args[code_flag + 1], is_shell, raw, depth, env)
            return
        plain = [args[i] for i in cmds.positionals(args, ("-W", "-X", "-m", "-r"))]
        if plain and plain[0] != "-" and "-m" not in args:
            self._executed_file(plain[0], name, raw, depth)

    def _executed_file(self, path_text, interpreter, raw, depth):
        normal = self.policy.normalize(path_text, self.cwd)
        content = self.files.get(normal) if normal else None
        if content is not None:
            self.code(content, interpreter in rules.SHELLS or interpreter == "sh", raw, depth, None)

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
        self.scan_fragments(text, raw)
        match = _ENV_WHOLE_RE.search(text)
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

    # -- here-documents ----------------------------------------------------------------------
    def _heredocs(self, item, depth, flags, data_only):
        command = item.cmd
        if not command.heredocs:
            return
        name = cmds.name_of(item.argv[0]) if item.argv else ""
        is_code = bool(item.argv) and not data_only and (
            self._executes_stdin(item.argv) or (item.group in flags["sink"] and name in ("cat", "echo", "printf")))
        for doc in command.heredocs:
            if is_code:
                self.code(doc.body, name in rules.SHELLS, command.raw, depth, None)
            else:
                for secret in rules.SECRET_NAME_RE.finditer(doc.body):
                    self.add("secret-env-in-file", command.raw, secret.group(0))


def _quote(word):
    return "'" + word.replace("'", "'\\''") + "'"
