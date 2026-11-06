"""Processes that inline code starts or signals (T062): `os.system`, `subprocess.*`, Node's `child_process`, Ruby's and
Perl's `system`/backticks, and `os.kill`/`process.kill`/`Process.kill`/Perl `kill`.

A command inline code runs is audited like a command the agent typed, so `os.system('gh api user')` is `cmd-gh` and
`subprocess.run(['git', 'push', 'origin', 'HEAD'])` is `cmd-git-push`. Only literal pieces are known: a plain string,
a name bound to one literal (`cmd = 'pkill x'`, `argv = ['pkill', 'x']`), an f-string or `%`/`.format` template
(its holes are unknown), and `'...'.split()`/`shlex.split('...')`. A command whose program is unknown is not audited.
"""

import re

from rigor_lib.trajectory_literals import (_ASSIGN_RE, _NAME_RE, _STRING_RE, _args, _inert_spans, _split_args,
                                           _unquote)

UNKNOWN = '"${_rigor_unknown}"'  # an unset variable: the shell analysis sees an unknown piece
_PREFIX_RE = re.compile(r"[A-Za-z]*")
# a shell command string: os.system(S), os.popen(S), subprocess.getoutput(S), Node's execSync(S)/cp.exec(S)
_SHELL_CALL_RE = re.compile(
    r"(?<![\w$.])(?:os\.(?:system|popen)|subprocess\.(?:getoutput|getstatusoutput)|commands\.getoutput|"
    r"(?:asyncio\.)?create_subprocess_shell|"
    r"(?:child_process|cp|require\(\s*['\"](?:node:)?child_process['\"]\s*\))\.(?:exec|execSync)|execSync)\s*\(")
# an argv (or a string with shell=True): subprocess.run/call/check_*/Popen, os.exec*/spawn*, Node spawn/execFile
_ARGV_CALL_RE = re.compile(
    r"(?<![\w$.])(?:subprocess\.(?P<sub>run|call|check_call|check_output|Popen)|"
    r"os\.(?P<osx>exec[lv]p?e?|spawn[lv]p?e?|posix_spawnp?)|"
    r"(?:(?:child_process|cp|require\(\s*['\"](?:node:)?child_process['\"]\s*\))\.)?"
    r"(?P<node>spawn|spawnSync|execFile|execFileSync)|"
    r"(?:asyncio\.)?(?P<aexec>create_subprocess_exec)|(?P<sys>system|exec))\s*\(")
_RUBY_PERL = ("ruby", "perl")
_BARE_SYSTEM_RE = re.compile(r"(?<![\w$.:])(?:system|exec|spawn)[ \t]+(?=[\[\"'])")
_BACKTICK_RE = re.compile(r"`([^`\n]*)`|%x\{([^}\n]*)\}|%x\(([^)\n]*)\)|\bqx\{([^}\n]*)\}|\bqx\(([^)\n]*)\)")
_LIST_ASSIGN_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*=\s*[\[(]")
_HOLE_F_RE = re.compile(r"\{[^{}]*\}")
_HOLE_PCT_RE = re.compile(r"%[-#0 +]*[0-9.]*[sdirfx]")
# kill calls: (regex, index of the pid argument)
_KILL_CALLS = (
    (re.compile(r"(?<![\w$.])os\.kill(?:pg)?\s*\("), 0),
    (re.compile(r"(?<![\w$.])signal\.pthread_kill\s*\("), 0),
    (re.compile(r"(?<![\w$.])process\.kill\s*\("), 0),
    (re.compile(r"(?<![\w$.])psutil\.Process\s*\("), 0),
    (re.compile(r"(?<![\w$.:])Process\.kill\s*\("), 1),
)
_PERL_KILL_RE = re.compile(r"(?<![\w$.>-])kill(?![\w-])\s*\(?\s*")
_PSUTIL_SIGNAL_RE = re.compile(r"\s*\.\s*(?:kill|terminate|send_signal)\s*\(")
_SPAWN_RE = re.compile(r"(?:subprocess\.Popen|Popen|multiprocessing\.Process|Process|create_subprocess_(?:exec|shell)|"
                       r"spawn|fork|os\.fork|os\.posix_spawnp?|os\.spawn[lv]p?e?|pty\.fork)\s*\(")
_SELF_PIDS = ("os.getpid()", "process.pid", "$$", "Process.pid", "os.getpgrp()", "os.getpgid(0)", "0")


def _names(text):
    names = {}
    for match in _ASSIGN_RE.finditer(text):
        names.setdefault(match.group(1), []).append(_unquote(match.group(2)))
    return names


def _lists(text):
    """{name: [element texts]} of `name = [ ... ]` / `name = ( ... )` assignments."""
    found = {}
    for match in _LIST_ASSIGN_RE.finditer(text):
        found.setdefault(match.group(1), []).append(_split_args(_args(text, match.end())))
    return found


def _template(arg):
    """The literal text of a string argument, with the holes of an f-string or a `%`/`.format` template unknown;
    None when the argument is not one."""
    arg = arg.strip()
    match = _STRING_RE.match(arg)
    if match is None:
        return None
    rest = arg[match.end():].strip()
    body = _unquote(match.group(0))
    prefix = _PREFIX_RE.match(match.group(0)).group(0).lower()
    if "f" in prefix or rest.startswith(".format"):
        body = _HOLE_F_RE.sub(UNKNOWN, body)
    elif rest.startswith("%"):
        body = _HOLE_PCT_RE.sub(UNKNOWN, body)
    elif rest:
        return None
    return body


def _scalar(arg, names):
    """A string argument's text, or the single literal a name is bound to; None when unknown."""
    text = _template(arg)
    if text is not None:
        return text
    arg = arg.strip()
    if _NAME_RE.fullmatch(arg) is not None and len(set(names.get(arg, ()))) == 1:
        return names[arg][0]
    return None


def _quote(word):
    return "'" + word.replace("'", "'\\''") + "'"


def _argv_command(arg, names, lists):
    """The shell text of an argv argument (`['git', 'push']`, a name bound to such a list, `'a b'.split()`,
    `shlex.split('a b')`); None when its program is unknown."""
    arg = arg.strip()
    split = re.fullmatch(r"(?:shlex\.split\s*\((.*)\)|(.*?)\s*\.\s*split\s*\(\s*\))", arg, re.DOTALL)
    if split is not None:
        text = _scalar(split.group(1) or split.group(2), names)
        return text
    elements = None
    if arg[:1] in "[(" and arg[-1:] in "])":
        elements = _split_args(arg[1:-1])
    elif _NAME_RE.fullmatch(arg) is not None and len(lists.get(arg, ())) == 1:
        elements = lists[arg][0]
    if elements is None:
        return None
    words = [_scalar(e, names) for e in elements if e.strip()]
    if not words or words[0] is None or UNKNOWN in words[0]:
        return None
    return " ".join(_quote(w) if w is not None and UNKNOWN not in w else (w or UNKNOWN) for w in words)


def commands(text, lang=None):
    """The shell command texts that inline code runs (see the module docstring)."""
    names, lists = _names(text), _lists(text)
    inert = _inert_spans(text, comments=True)
    is_text = lambda at: any(start <= at < end for start, end in inert)  # noqa: E731
    found = []
    for call in _SHELL_CALL_RE.finditer(text):
        args = _split_args(_args(text, call.end()))
        if not is_text(call.start()) and args:
            command = _scalar(args[0], names)
            if command is not None and command.strip():
                found.append(command)
    for call in _ARGV_CALL_RE.finditer(text):
        if is_text(call.start()):
            continue
        args = [a for a in _split_args(_args(text, call.end())) if a]
        positional = [a for a in args if re.match(r"[A-Za-z_]\w*\s*=(?!=)", a) is None]
        if not positional:
            continue
        if call.group("aexec") is not None:
            command = _system_command(positional, names, lists)  # (program, *args), like system()
        elif call.group("sys") is not None:
            if call.group("sys") == "exec" and lang not in _RUBY_PERL:
                continue  # Python's exec() runs Python (its text is searched for fragments elsewhere)
            command = _system_command(positional, names, lists)
        elif call.group("osx") is not None:
            command = _os_exec_command(call.group("osx"), positional, names, lists)
        elif call.group("node") is not None:
            command = _node_command(positional, names, lists)
        else:
            command = _argv_command(positional[0], names, lists)
            if command is None:
                command = _scalar(positional[0], names)  # a string: with shell=True a command line, else a program
        if command is not None and command.strip():
            found.append(command)
    if lang in _RUBY_PERL:
        for call in _BARE_SYSTEM_RE.finditer(text):  # `system "cmd"`, `exec 'a', 'b'` without parentheses
            if not is_text(call.start()):
                tail = text[call.end():call.end() + 2000].split("\n", 1)[0]
                positional = _split_args(re.split(r"\s(?:or|and|if|unless)\s|;|\|\||&&", tail, maxsplit=1)[0])
                command = _system_command([a for a in positional if a], names, lists) if positional else None
                if command is not None and command.strip():
                    found.append(command)
        for match in _BACKTICK_RE.finditer(text):
            body = next(g for g in match.groups() if g is not None)
            if body.strip() and not is_text(match.start()):
                found.append(body)
    return found


def _system_command(positional, names, lists):
    """Ruby/Perl/Python `system(...)`: one string is a command line, several are an argv."""
    if len(positional) == 1:
        return _argv_command(positional[0], names, lists) or _scalar(positional[0], names)
    return _argv_command("[" + ", ".join(positional) + "]", names, lists)


def _os_exec_command(kind, positional, names, lists):
    """os.execv(path, argv), os.execlp(file, arg0, arg1, ...), os.spawnv(mode, path, argv), os.posix_spawn(path, argv)."""
    if kind.startswith("spawn"):
        positional = positional[1:]  # the mode
    if len(positional) < 2:
        return None
    program = _scalar(positional[0], names)
    if program is None:
        return None
    if "v" in kind or kind.startswith("posix_spawn"):
        rest = _argv_command(positional[1], names, lists)
        args = rest.split(" ", 1)[1] if rest and " " in rest else ""
    else:
        tail = [_scalar(a, names) for a in positional[2:]]
        tail = [t for t in tail if t is not None and not t.startswith("os.environ")]
        args = " ".join(_quote(t) for t in tail)
    return (_quote(program) + " " + args).strip()


def _node_command(positional, names, lists):
    """spawn(cmd, [args], {shell}) / execFile(file, [args])."""
    program = _scalar(positional[0], names)
    if program is None:
        return None
    rest = _argv_command(positional[1], names, lists) if len(positional) > 1 else None
    if rest is None and len(positional) > 1 and positional[1].strip().startswith("["):
        return None
    words = _quote(program) if " " not in program else program
    return words + (" " + rest if rest else "")


def kill_targets(text, lang=None):
    """The pid argument texts of the signal calls in inline code (os.kill, os.killpg, process.kill, Process.kill,
    psutil.Process(pid).kill(), Perl's `kill SIG, PID...`)."""
    inert = _inert_spans(text, comments=True)
    is_text = lambda at: any(start <= at < end for start, end in inert)  # noqa: E731
    found = []
    for regex, index in _KILL_CALLS:
        for call in regex.finditer(text):
            region = _args(text, call.end())
            if is_text(call.start()):
                continue
            if "psutil" in call.group(0) and _PSUTIL_SIGNAL_RE.match(text, call.end() + len(region) + 1) is None:
                continue
            args = _split_args(region)
            found.extend(args[index:] if index else args[:1])
    if lang == "perl":
        for call in _PERL_KILL_RE.finditer(text):
            if is_text(call.start()):
                continue
            tail = text[call.end():call.end() + 400].split(";", 1)[0]
            args = _split_args(tail.rstrip(") \t\n"))
            found.extend(args[1:])
    return [a.strip() for a in found if a.strip()]


def own_target(pid, text, own_pids):
    """True when a pid expression of `text` names a process the agent started (or itself): a literal pid in
    `own_pids`, `os.getpid()`, `X.pid` (also `os.getpgid(X.pid)`, `-X.pid`) of a process the same code spawned,
    or a name bound to one of those."""
    pid = pid.strip().lstrip("-").strip()
    for _ in range(4):
        group = re.fullmatch(r"os\.getpgid\s*\((.*)\)", pid, re.DOTALL)
        if group is None:
            break
        pid = group.group(1).strip()
    if pid.isdigit():
        return pid in own_pids
    if pid.replace(" ", "") in _SELF_PIDS:
        return True
    attr = re.fullmatch(r"([A-Za-z_$]\w*)\s*\.\s*pid", pid)
    name = attr.group(1) if attr else (pid if re.fullmatch(r"\$?[A-Za-z_]\w*", pid) else None)
    if name is None:
        return False
    bare = name.lstrip("$")
    for match in re.finditer(r"(?<![\w.])\$?" + re.escape(bare) + r"\s*=(?!=)\s*(?:await\s+)?([^\n;]*)", text):
        value = match.group(1)
        if attr is not None and _SPAWN_RE.search(value):
            return True  # p = subprocess.Popen(...); os.kill(p.pid, ...)
        if attr is None and (_SPAWN_RE.search(value) or re.match(r"[A-Za-z_]\w*\s*\.\s*pid\b", value)):
            inner = re.match(r"([A-Za-z_]\w*)\s*\.\s*pid\b", value)
            if inner is None or own_target(inner.group(0), text, own_pids):
                return True  # pid = os.fork() / pid = p.pid
    return False
