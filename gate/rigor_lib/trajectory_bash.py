"""The Bash-tool analysis of `rigor trajectory`, plus the shared stateful analyzer."""

import fnmatch
import os
import posixpath
import re

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_rules as rules
from rigor_lib import trajectory_shell as shell
from rigor_lib.trajectory_code import CodeMixin
from rigor_lib.trajectory_flow import FlowMixin
from rigor_lib.trajectory_git import GitMixin
from rigor_lib.trajectory_paths import expand_braces, is_url
from rigor_lib.trajectory_proof import CallFacts, ProofMixin
from rigor_lib.trajectory_shell import DOLLAR, UNRESOLVED
from rigor_lib import trajectory_writers as writers

_VAR_RE = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*|[0-9@#?$!*-]))")
_LIVE_RE = re.compile(r"\$(\{?)(!?)([A-Za-z_][A-Za-z0-9_]*)([*@]?)")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CODE_LIKE = re.compile(r"[\s;()'\"]")
_FRAGMENTS = (
    (re.compile(r"/var/tmp/\.config(?![\w.-])"), "read-secret-dir"),
    (re.compile(r"/var/tmp/\.claude"), "read-claude-state"),
    (re.compile(r"(?:^|[/\s'\"=:~])\.ssh(?![\w.-])"), "read-ssh-material"),
    (re.compile(r"/proc/(?:self|thread-self|\d+)/environ"), "read-process-environ"),
    (re.compile(r"(?:^|[/\s'\"=])[\w.-]+-hidden(?:\.git)?(?![\w.-])"), "read-hidden-repo"),
    (re.compile(r"/annas-mcp(?![\w-])"), "read-clean-room"),
)
# T062 (R008 #19): absolute paths into a cache or a worktree dir, inside program text; read_rule() decides (own is fine)
_SEG = r"[^\s/'\"<>(){}\[\];|&,`$\\#:=@!%^]+"  # also a sed `s` or awk delimiter
_PATH_FRAGMENTS = (
    re.compile(r"(?<![\w.~-])" + re.escape(rules.CACHE_ROOT.rstrip("/")) + r"/" + _SEG + r"(?:/" + _SEG + r")*"),
    re.compile(r"(?<![\w.~-])/(?:" + _SEG + r"/)*?wt/" + _SEG + r"/" + _SEG + r"(?:/" + _SEG + r")*"),
)
_PATH_FRAGMENT_RULES = ("read-other-cache", "read-other-worktree")
_AWK_NAMES = ("awk", "gawk", "mawk", "nawk", "busybox-awk")
_SED_NAMES = ("sed", "gsed")
_AWK_ENVIRON_RE = re.compile(r"\bENVIRON\b(?!\s*\[)")  # the whole array (`for (k in ENVIRON)`), not one entry
_READERS = ("cat", "head", "tail", "less", "more", "grep", "rg", "ag", "sed", "awk", "xxd", "strings", "od",
            "base64", "cp", "ls", "find", "tar", "zip", "wc", "sort", "diff", "cmp", "file", "stat", "source", ".")
_DATA_SKIP_OPTS = ("-m", "--message", "--author", "--date", "-S")
_NON_PATH_OPTS = ("--pid=", "--lines=", "--bytes=", "--max-count=", "--sleep-interval=", "--max-unchanged-stats=")
_ATTACHED_RE = re.compile(r"(?:-[A-Za-z]|@)((?:/|~|\.\.?/|" + UNRESOLVED + r"|\$).*)\Z", re.DOTALL)
_TILDE_DIR_RE = re.compile(r"~([+-])(?=/|\Z)")
DIRSTACK = " dirstack"  # env key of the pushd stack (a name no shell variable can have)
# with the working directory unknown, a relative path starting at one of these is a forbidden read (T052, R008 #6)
_UNKNOWN_CWD_FIRST = ((re.compile(r"\.config\Z"), "read-secret-dir"), (re.compile(r"\.claude"), "read-claude-state"),
                      (re.compile(r"\.ssh\Z"), "read-ssh-material"),
                      (re.compile(r"(?:[ATRP]\d{3}|val-.*)\Z"), "read-other-worktree"))
_TRIM_RE = re.compile(r"(%%|%|##|#)(.*)\Z", re.DOTALL)


_DECLARERS = ("export", "declare", "typeset", "local", "readonly")
# variables whose value a program runs as a command (T057, R008 #10)
_COMMAND_VAR_RE = re.compile(r"\A(?:[A-Z0-9_]*_(?:PAGER|EDITOR)|PAGER|EDITOR|VISUAL|GIT_SSH_COMMAND|GIT_SSH)\Z")
_DECLARED_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", re.DOTALL)


def _declared(args):
    """{NAME: value} of the `NAME=value` words of `export`, `declare -x` and the like."""
    found = {}
    for arg in args:
        match = _DECLARED_RE.match(arg)
        if match is not None:
            found[match.group(1)] = match.group(2)
    return found


def trim_value(value, op, pattern):
    """`${v#p}`, `${v##p}`, `${v%p}`, `${v%%p}` for a known value (shell glob patterns)."""
    size = len(value)
    if op in ("#", "##"):
        cuts = range(size + 1) if op == "#" else range(size, -1, -1)
        return next((value[i:] for i in cuts if fnmatch.fnmatchcase(value[:i], pattern)), value)
    cuts = range(size, -1, -1) if op == "%" else range(size + 1)
    return next((value[:i] for i in cuts if fnmatch.fnmatchcase(value[i:], pattern)), value)


def excerpt_around(raw, token):
    raw = raw.strip()
    if len(raw) <= rules.MAX_EXCERPT or not token:
        return raw
    at = raw.find(token)
    if at < 0:
        return raw
    start = max(0, at - 40)
    return raw[start:start + rules.MAX_EXCERPT]


_MKTEMP_FLAGS = re.compile(r"-[duqt]+\Z")
_MKTEMP_X = re.compile(r"XXX")


ARRAY = "[]"  # env key suffix of an array: env["NAME[]"] is the tuple of its elements (T074)
_ARRAY_CALL_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\[@\]\}")


class Prepared:
    __slots__ = ("cmd", "argv", "extra", "words", "group", "cwd", "inner", "wrapped", "job_dir", "job_skip", "clean_env",
                 "prefix_values", "env_values")

    def __init__(self, cmd, argv, extra, words, cwd):
        self.cmd = cmd
        self.argv = argv      # expanded, wrappers and keywords removed
        self.extra = extra    # rule ids found while unwrapping
        self.words = words    # expanded words before unwrapping
        self.group = cmd.group
        self.cwd = cwd        # the working directory this command runs in
        self.inner = None     # for `tools/job run ... -- CMD`: CMD, audited as if it ran here directly
        self.wrapped = False  # this is such a CMD: the redirections and here-documents belong to tools/job
        self.job_dir = None   # the job directory `tools/job run` writes (`--dir`, else `$TMPDIR/jobs`)
        self.job_skip = set()  # argv index of the `--dir` value: a write target, not a read
        self.clean_env = False  # `env -i` (with no secret-looking name) emptied the environment it runs in
        self.prefix_values = []  # (NAME, value) of the `NAME=value` words in front of the command (T057, R008 #10)
        self.env_values = []     # (NAME, value) of the `env NAME=value` wrappers stripped in front of this argv


class Analyzer(CodeMixin, FlowMixin, GitMixin, ProofMixin, writers.WritersMixin):
    delete_recursive = True  # whether the delete being judged can remove a tree; `_write_targets` sets it (T077)

    def __init__(self, policy, task):
        self.policy = policy
        self.task = task
        self.cwd = policy.worktree
        self.hits = []
        self.created = set()
        self.read_set = set()
        self.env_now = {}
        self.prefix_words = []  # assignments and wrappers in front of the command being analysed
        self.iterations = 0   # loop bodies run in this Bash call (bounded)
        self.files = {}       # normalized path -> content the agent wrote (for later execution)
        self.known_before = None  # the file the latest write touched, if its text was known just before
        self.dirty = set()    # files in `files` that were changed afterwards by something we did not model
        self.unknown = set()  # files the transcript wrote with a text the audit does not know (T049, R008 #3)
        self.clones = {}      # local clones the agent made: dir -> origin no longer proven (see GitMixin)
        self.aliases = {}     # executable path the agent made -> source basename (cp/ln/install/mv, T057 R008 #12)
        self.cwd_stack = []   # working directories to return to when a `( ... )` subshell closes
        self.own_pids = set()  # process ids the agent started (printed by tools/job run, a background command)
        self.clean_env = False  # the command being analysed runs under `env -i`
        self.added_all = False  # the agent staged the whole worktree (`git add -A`/`.`/`-u`): all of it is tracked
        self.added = set()    # worktree paths the agent staged with `git add PATH` (T052, ruling 7)
        self.facts = None     # CallFacts of the Bash call being analysed (trajectory_proof, T052)
        self.grade_outputs = set()  # stdout files of grade keep runs, not written by anything else since
        self.call_outputs = set()   # the same for canary keep runs, within the current call only
        self.cmd_env = {}     # the environment the command being analysed sees, as far as it is known (T057)
        self.binding = False  # expanding the values of a plain assignment (no command on the line, T074)
        self.dirs = set()     # directories the transcript made (mkdir, tar -C, unzip -d): copy targets (T061)

    # -- plumbing ----------------------------------------------------------------------------
    def add(self, rule, raw, token=""):
        self.hits.append((rule, excerpt_around(raw, token)))

    def drain(self):
        found, self.hits = self.hits, []
        return found

    def record_file(self, path_text, content):
        normal = self.policy.normalize(path_text, self.cwd)
        if normal is not None and isinstance(content, str):
            self.files[normal] = content
            self.dirty.discard(normal)
            self.unknown.discard(normal)

    def base_env(self):
        return {"HOME": self.policy.home, "PWD": self.cwd}

    # -- expansion ---------------------------------------------------------------------------
    def expand(self, word, env):
        def replace(match):
            inner = match.group(1) if match.group(1) is not None else match.group(2)
            name = _NAME_RE.match(inner)
            if inner == "!":
                return rules.BACKGROUND_PID  # the last background job: a process the agent started
            if name is None and inner in env and inner[0] in "0123456789@#*":
                return env[inner]  # a positional parameter bound by the caller of a written script
            if name is None or inner.startswith("!"):
                return UNRESOLVED
            rest = inner[name.end():]
            if rest == "[0]" and name.group(0) == "BASH_SOURCE":
                rest = ""  # `${BASH_SOURCE[0]}`: the script being run, bound by its caller (T052)
            value = env.get(name.group(0))
            if rest == "":
                return UNRESOLVED if value is None else value
            trim = _TRIM_RE.match(rest)
            if trim is not None and value is not None and UNRESOLVED not in value + trim.group(2):
                return trim_value(value, trim.group(1), trim.group(2))
            if rest.startswith(":-"):
                return value if value else rest[2:]
            if rest.startswith("-"):
                return rest[1:] if value is None else value
            return UNRESOLVED
        text = self._static_subs(word, env)
        text = _VAR_RE.sub(replace, text)
        tilde = _TILDE_DIR_RE.match(text)
        if tilde is not None:  # `~+` is $PWD, `~-` is $OLDPWD (T052, R008 #6)
            text = env.get("PWD" if tilde.group(1) == "+" else "OLDPWD", UNRESOLVED) + text[2:]
        if text == "~" or text.startswith("~/"):
            text = self.policy.home + text[1:]
        return text.replace(DOLLAR, "$")

    def _static_subs(self, word, env):
        """Replace command substitutions whose output is known without running anything."""
        if UNRESOLVED not in word.text:
            return word.text
        pieces = word.text.split(UNRESOLVED)
        out = [pieces[0]]
        for index, rest in enumerate(pieces[1:]):
            known = self._static_value(word.subs[index], env) if index < len(word.subs) else None
            out.append(UNRESOLVED if known is None else known)
            out.append(rest)
        return "".join(out)

    def _static_value(self, text, env):
        found = shell.parse(text)
        if not found or len(found) > 2 or any(c.assigns or c.redirects or c.heredocs or not c.words for c in found):
            return None
        words = [self.expand(w, env) for w in found[0].words]
        if any(UNRESOLVED in w for w in words):
            return None
        name, args = words[0], words[1:]
        if len(found) == 2:  # `cd DIR && pwd` (T052): the directory a script locates itself in
            second = [w.text for w in found[1].words]
            if name == "cd" and len(args) == 1 and second == ["pwd"] and found[1].group != found[0].group:
                return self.policy.normalize(args[0], self.cwd)
            return None
        if name == "dirname" and len(args) == 1:
            return posixpath.dirname(args[0].rstrip("/") or "/") or "."
        if any(w.subs for w in found[0].words):
            return None
        if name == "mktemp" and self.binding:
            return self._mktemp(args, env)
        if name == "pwd" and not args:
            return self.cwd
        if name == "git" and args == ["rev-parse", "--show-toplevel"]:
            return self.policy.worktree
        if name == "echo":
            return " ".join(a for a in args if a != "-n")
        if name == "printf" and len(args) >= 2 and args[0] == "%s":
            return "".join(args[1:])
        return None

    def _mktemp(self, args, env):
        """The path `mktemp` prints, for a plain assignment `NAME=$(mktemp ...)` (T074): a fresh unique name under `-p DIR`, else `$TMPDIR`, else unresolved (not guessed:
        the real default `/tmp` is outside every lane's scratch, and the lane's own TMPDIR is not visible to the audit). A template
        keeps its own directory. An option the audit does not model leaves the value unresolved. The result is judged
        like any other path: `TMPDIR=/etc` or `-p /etc` makes the later uses of it block."""
        tmpdir, template, relative, index = None, None, False, 0
        while index < len(args):
            arg = args[index]
            index += 1
            if arg in ("-p", "--tmpdir") and index < len(args):
                tmpdir, index = args[index], index + 1
            elif arg.startswith("--tmpdir="):
                tmpdir = arg[len("--tmpdir="):]
            elif _MKTEMP_FLAGS.match(arg):
                relative = relative or "t" in arg
            elif arg.startswith("-") or template is not None:
                return None
            else:
                template = arg
        if template is not None and not _MKTEMP_X.search(template):
            return None  # no run of `XXX`: mktemp fails, prints nothing
        if tmpdir is None and (relative or template is None):
            tmpdir = env.get("TMPDIR")
            if tmpdir is None:
                return None  # the default is /tmp, but the lane's TMPDIR is not known here: not guessed (T074)
        if tmpdir is not None and (not tmpdir or UNRESOLVED in tmpdir):
            return None
        name = "tmp.XXXXXXXXXX" if template is None else template
        if tmpdir is None:
            return None if template is None or UNRESOLVED in self.cwd else posixpath.join(self.cwd, name)
        return posixpath.join(tmpdir, name)

    # -- entry point -------------------------------------------------------------------------
    def bash(self, text, depth=0, env=None):
        if depth > rules.MAX_DEPTH:
            self.add("nesting-too-deep", text)
            return
        if depth == 0:
            self.iterations = 0
            self.facts, self.call_outputs = CallFacts(), set()
        env = dict(self.base_env() if env is None else env)
        start, stack, self.cwd_stack = self.cwd, self.cwd_stack, []
        self.run_commands(shell.parse(text), env, depth)
        self.cwd_stack = stack
        if depth > 0:
            self.cwd = start  # a substitution, `bash -c` or script runs in a child: its `cd` stays inside

    def _scope(self, depth):
        """Leave the `( ... )` subshells that closed since the last command, enter those that opened."""
        while len(self.cwd_stack) > depth:
            self.cwd = self.cwd_stack.pop()
        while len(self.cwd_stack) < depth:
            self.cwd_stack.append(self.cwd)

    def _change_dir(self, argv, env, raw):
        """`cd`, `pushd`, `popd` (T052, R008 #6). `cd` alone goes home, `cd -` to `$OLDPWD`, `pushd DIR` keeps the old
        directory on a stack (`env[DIRSTACK]`, per call like the shell's), `pushd` alone swaps, `popd` returns. A target
        the audit cannot know (`cd "$(...)"`, `$OLDPWD` unset in this call, a relative target while `CDPATH` is set,
        `pushd +N`) makes the working directory unknown: later relative paths are unresolved until an absolute `cd`."""
        name = cmds.name_of(argv[0])
        args = [a for a in argv[1:] if a not in ("-P", "-L", "-e", "-@", "--", "-n")]
        stack = list(env.get(DIRSTACK, ()))
        old = self.cwd
        if name == "popd":
            if args:
                target = UNRESOLVED
            elif not stack:
                return  # `popd: directory stack empty`: nothing changes
            else:
                target = stack.pop()
        elif name == "pushd" and not args:
            if not stack:
                return
            target, stack[-1] = stack[-1], old
        elif not args:
            target = self.policy.home
        elif args[0] == "-" and name == "cd":
            target = env.get("OLDPWD", UNRESOLVED)
        elif args[0].startswith(("+", "-")) and name == "pushd":
            target = UNRESOLVED
        elif env.get("CDPATH") and not args[0].startswith(("/", "./", "../", "~")) and args[0] not in (".", ".."):
            target = UNRESOLVED  # CDPATH may send a relative `cd` anywhere: each place it names is checked
            for entry in env["CDPATH"].split(":"):
                if entry and UNRESOLVED not in entry:
                    self.read_word(entry.rstrip("/") + "/" + args[0], raw, "cd")
        else:
            target = self.policy.normalize(args[0], old) or UNRESOLVED
        if name == "pushd" and args:
            stack.append(old)
        env[DIRSTACK] = tuple(stack)
        env["OLDPWD"] = old
        self.cwd = target
        env["PWD"] = target

    def flush(self, prepared, depth, env):
        flags = self._pipeline_flags(prepared)
        final = self.cwd
        for item in prepared:
            while item is not None:
                self.analyze(item, flags, depth, env)
                item = item.inner
        self.cwd = final

    def _pipeline_flags(self, prepared):
        """group -> True when the pipeline decodes text and a later stage executes stdin."""
        state, flagged = {}, {}
        for item in prepared:
            if not item.argv:
                continue
            if cmds.decodes_input(item.argv):
                state[item.group] = True
            if state.get(item.group) and self._executes_stdin(item.argv):
                flagged[item.group] = True
        sinks, producer, feeder, last = {}, {}, {}, {}
        for item in prepared:
            if item.group in last:
                feeder[id(item)] = last[item.group]  # the stage whose output is this one's stdin
            if item.argv and self._executes_stdin(item.argv):
                sinks[item.group] = True
                if item.group in last:
                    producer[id(item)] = last[item.group]  # the same, for an interpreter (T049)
            last[item.group] = item
        return {"obfuscated": flagged, "sink": sinks, "producer": producer, "feeder": feeder}

    @staticmethod
    def _executes_stdin(argv):
        name = cmds.name_of(argv[0])
        if name in ("eval", "source", "."):
            return name == "eval" and len(argv) == 1
        if name not in rules.INTERPRETERS and cmds.interpreter_kind(name) is None:
            return False
        args = argv[1:]
        if cmds.code_word(name, args)[1]:
            return False
        plain = [args[i] for i in cmds.positionals(args, ("-W", "-X", "-m", "-r"))]
        return not plain or plain[0] in cmds.STDIN_PATHS  # `/dev/stdin` and the like are `-` (T049)

    # -- preparation -------------------------------------------------------------------------
    def prepare(self, command, env, depth):
        self._scope(command.depth)
        here = self.cwd
        for word in self._all_words(command):
            for sub in word.subs:
                self.bash(sub, depth + 1, env)
        for doc in command.heredocs:
            if not doc.quoted:  # T049 (R008 #1): the shell expands an unquoted body before anyone reads it
                subs, names = shell.body_expansions(doc.body)
                for sub in subs:
                    self.bash(sub, depth + 1, env)
                self._live_secrets(shell.Word(" ".join(names), [], False), command.raw)
        for name, word in command.assigns:
            if rules.SECRET_NAME_RE.fullmatch(name):
                self.add("secret-env-mention", command.raw, name)
            self._live_secrets(word, command.raw)
        self.binding = not command.words  # `NAME=$(mktemp ...)` alone on its line is modelled (T074)
        self._forget_arrays(command, env)
        values = {name: self.expand(word, env) for name, word in command.assigns}
        self.binding = False
        if not command.words:
            env.update(values)
            for name, word in command.assigns:  # `NAME=(a b)`: the elements, when all are known (T074)
                elements = tuple(self.expand(w, env) for w in word.array) if word.array is not None else None
                if elements is None or any(UNRESOLVED in e for e in elements):
                    env.pop(name + ARRAY, None)
                else:
                    env[name + ARRAY] = elements
            item = Prepared(command, [], [], [], here)
            item.prefix_values = list(values.items())
            return item
        for word in command.words:
            self._live_secrets(word, command.raw)
        words = self._words(command, env)
        item = self._unwrapped(command, words, here, values.get("TMPDIR", env.get("TMPDIR")), 0)
        link = item
        while link is not None:  # CMD of `tools/job run` inherits the prefix assignments too
            link.prefix_values = list(values.items())
            link = link.inner
        if item.argv and cmds.name_of(item.argv[0]) in ("cd", "pushd", "popd"):
            self._change_dir(item.argv, env, command.raw)
        elif item.argv and cmds.name_of(item.argv[0]) in _DECLARERS:
            env.update(_declared(item.argv[1:]))  # `export NAME=value` binds it for the commands after it
        return item

    @staticmethod
    def _unwrap(argv):
        """(argv without leading keywords and wrappers such as `timeout`, the rule ids the wrappers hit)."""
        extra = []
        for _ in range(8):
            while argv and argv[0] in cmds.KEYWORDS:
                argv = argv[1:]
            if not argv:
                break
            inner, more = cmds.unwrap_once(argv)
            if inner is None:
                break
            extra.extend(more)
            argv = inner
        return argv, extra

    def _unwrapped(self, command, words, here, tmpdir, nest, clean=False):
        """The Prepared item for `words`. `tools/job run [OPTS] NAME -- CMD` becomes two items: the tools/job
        call itself (its argv ends before `--`; it writes its job directory) and, as `inner`, CMD exactly as if
        it had been run directly at this point (wrappers inside CMD are unwrapped in turn)."""
        argv, extra = self._unwrap(list(words))
        assigns, emptied = cmds.env_wrappers(words[:len(words) - len(argv)])
        chdir = cmds.env_chdir(words[:len(words) - len(argv)])
        if chdir is not None:  # `env -C DIR CMD` runs CMD in DIR (T052, R008 #6)
            here = self.policy.normalize(chdir, here) or UNRESOLVED
        if emptied:
            tmpdir = None  # `env -i`: only what it assigns is left
        tmpdir = assigns.get("TMPDIR", tmpdir)
        clean = (clean or emptied) and not any(rules.SECRET_NAME_RE.search(n) for n in assigns)
        if clean and "cmd-env-dump" in extra and cmds.clean_environment(assigns, emptied):
            extra.remove("cmd-env-dump")  # `env -i A=b` alone prints only A=b
        job = cmds.job_run(argv) if argv and nest < 8 else None
        if job is None:
            item = Prepared(command, argv, extra, words, here)
            item.clean_env = clean
            item.env_values = list(assigns.items())
            return item
        dir_index, cut = job
        own = argv[:cut]
        item = Prepared(command, own, extra, words[:len(words) - len(argv)] + own, here)
        item.clean_env = clean
        item.env_values = list(assigns.items())
        if dir_index is not None:
            item.job_skip = {dir_index}
            text = own[dir_index]
            item.job_dir = text[len("--dir="):] if text.startswith("--dir=") else text
        elif tmpdir:  # tools/job refuses an empty TMPDIR
            item.job_dir = tmpdir + "/jobs"
        item.inner = self._unwrapped(command, argv[cut + 1:], here, tmpdir, nest + 1, clean)
        item.inner.wrapped = True
        return item

    @staticmethod
    def _all_words(command):
        words = list(command.words) + [w for _, w in command.assigns] + [r.target for r in command.redirects]
        return words

    def _live_secrets(self, word, raw):
        for match in _LIVE_RE.finditer(word.text):
            brace, bang, name, tail = match.groups()
            if bang == "!" and brace and tail and re.search("[a-z]", name):
                continue  # `${!r1_*}` lists variable names; a prefix with a lowercase letter lists no secret name
            if bang == "!" or rules.SECRET_NAME_RE.fullmatch(name):
                self.add("secret-env-access", raw, match.group(0))

    # -- analysis ----------------------------------------------------------------------------
    @staticmethod
    def _forget_arrays(command, env):
        """A command that assigns, unsets or reads into an array name makes what the audit knows of it stale (T074):
        `NAME=x`, `NAME+=(x)`, `unset NAME`, `read -a NAME`, `printf -v NAME`, `declare -a NAME=(...)`, `for NAME in`."""
        texts = [w.text for w in command.words] + [name for name, _ in command.assigns]
        for key in [k for k in env if k.endswith(ARRAY)]:
            name = key[:-len(ARRAY)]
            if any(t == name or t.startswith((name + "=", name + "+=", name + "[")) for t in texts):
                del env[key]

    def _words(self, command, env):
        """The expanded words of a command. A command that starts with a known array, `"${NAME[@]}" ARGS`, starts with
        its elements (T074); any other use of an array stays what `expand` makes of it (unresolved)."""
        words = [self.expand(word, env) for word in command.words]
        first = _ARRAY_CALL_RE.fullmatch(command.words[0].text)
        elements = env.get(first.group(1) + ARRAY) if first is not None else None
        if elements:
            words[:1] = list(elements)
        return words

    def analyze(self, item, flags, depth, env):
        command = item.cmd
        raw = command.raw
        hits_before = len(self.hits)
        self.env_now = env
        self.prefix_words = [n for n, _ in command.assigns] + item.words[:len(item.words) - len(item.argv)]
        self.cwd = item.cwd
        for rule in item.extra:
            self.add(rule, raw, "")
        for redirect in [] if item.wrapped else command.redirects:
            self._redirect(command, redirect)
        argv = item.argv
        self.note_output(item, argv, depth, env)
        self.cmd_env = dict(env)
        self.cmd_env.update(item.prefix_values + item.env_values)
        self._assignment_values(item, raw, depth, env)
        if not argv:
            if not item.wrapped:
                self._heredocs(item, depth, flags, data_only=True)
            return
        name = cmds.name_of(argv[0])
        if not item.wrapped:
            self._literal_output(command, argv, name)
        if UNRESOLVED in argv[0]:
            self.add("cmd-unresolved", raw, argv[0].replace(UNRESOLVED, "$("))
        if item.group in flags["obfuscated"] and name in rules.INTERPRETERS + ("eval",):
            self.add("cmd-obfuscated-exec", raw, name)
        self._command_rules(argv, raw, name)
        self._command_strings(item, argv, name, raw, depth, env)
        data_skip = self._data_indexes(argv, name, item.group in flags["sink"])
        write_idx = self._write_targets(item, argv, raw)
        write_idx |= self.modelled_writes(item, argv, name, raw, flags)  # T061 (R008 #16)
        self._piped_text(item, argv, name, flags)
        if item.job_dir is not None:
            self.write(item.job_dir, "create", raw)
        self._read_words(item, argv, raw, name, write_idx | data_skip | item.job_skip)
        self._recursive_reads(argv, raw, name)
        self._secret_words(argv, raw, name, data_skip)
        for word in item.words[:len(item.words) - len(argv)]:
            for match in rules.SECRET_NAME_RE.finditer(word):
                self.add("secret-env-mention", raw, match.group(0))
        self._kill_rules(argv, raw, name)
        self.clean_env = item.clean_env
        self._program_texts(argv, name, raw)
        self._run_code(item, argv, name, raw, depth, env)
        self.stdin_code(item, argv, name, raw, depth, flags)
        if name == "git":
            self.git_config_code(argv, raw, depth, env)
            self.git_exec_strings(argv, raw, depth, env)
            self.git_shared_store(argv, raw)
            self.note_clone(argv, len(self.hits) == hits_before)
        self.clean_env = item.clean_env
        if not item.wrapped:
            self._heredocs(item, depth, flags, data_only=False)

    def _piped_text(self, item, argv, name, flags):
        """`cat <<EOF | tee [-a] f` (T072, B21): when the stage feeding `tee` is a plain `cat` of a known here-document,
        the text of f is that body, as for `cat <<EOF > f`. Any other feeder leaves f unknown."""
        feeder = flags["feeder"].get(id(item))
        if name != "tee" or item.wrapped or item.cmd.heredocs or feeder is None or feeder.wrapped:
            return
        if list(feeder.argv) != ["cat"] or len(feeder.cmd.heredocs) != 1 or \
                feeder.cmd.redirects or not known_body(feeder.cmd.heredocs[0]):
            return
        for index, op in cmds.write_specs(argv):
            self.keep_text(argv[index], op, feeder.cmd.heredocs[0].body)

    def _literal_output(self, command, argv, name):
        """`echo TEXT > f`, `printf FMT ARGS >> f` with a literal text: the content of f is known (T049)."""
        outs = [r for r in command.redirects if r.op in (">", ">>", ">|") and r.fd in (None, "1")]
        if name not in ("echo", "printf") or len(outs) != 1 or command.heredocs:
            return
        text = cmds.echo_text(argv) if name == "echo" else cmds.printf_text(argv)
        if text is not None:
            self.keep_text(self.expand(outs[0].target, self.env_now), "edit" if outs[0].op == ">>" else "rewrite",
                           text)

    def _kill_rules(self, argv, raw, name):
        """Rule `kill-foreign`: signals by process name, or to a pid the agent did not start (see own_pids)."""
        if name in rules.KILL_BY_NAME:
            self.add("kill-foreign", raw, name)
        elif cmds.kill_by_other_name(argv) is not None:  # T062 (R008 #20)
            self.add("kill-foreign", raw, cmds.kill_by_other_name(argv))
        elif name == "kill":
            targets = cmds.kill_targets(argv)
            if targets is None:
                return
            foreign = [t for t in targets if not self._own_target(t)]
            if foreign or not targets:  # no target: `... | xargs kill`, the pids come from another command
                self.add("kill-foreign", raw, name if not foreign or UNRESOLVED in foreign[0] else foreign[0])

    def _note_git_add(self, argv):
        """`git add` makes its worktree paths tracked (reviewed in the diff at merge), so running them later is not
        obfuscated even with content the audit could not see (T052, ruling 7)."""
        _, sub, sub_args = cmds.git_parts(argv)
        if sub not in ("add", "stage"):
            return
        for arg in sub_args:
            if arg in ("-A", "--all", "-u", "--update", ".", ":/", "*") or arg.startswith(":/"):
                self.added_all = True
            elif not arg.startswith("-"):
                rel = self.policy.relative_to_worktree(self.policy.normalize(arg, self.cwd) or "")
                if rel is not None:
                    self.added.add(rel)

    def worktree_tracked(self, normal):
        """True when `normal` is a worktree file git tracks on disk or the agent staged in this transcript."""
        rel = self.policy.relative_to_worktree(normal)
        return rel is not None and (self.added_all or rel in self.added or self.policy.is_tracked(rel))

    def _own_target(self, target):
        digits = target.lstrip("-")
        if target.startswith("%"):
            return UNRESOLVED not in target  # a job of this shell (`kill %1`, `kill $!`)
        return digits.isdigit() and digits in self.own_pids

    def _note_alias(self, argv):
        """`cp`/`ln`/`install`/`mv SRC DST`: if DST is later executed, it runs SRC's program (T057, R008 #12)."""
        name = cmds.name_of(argv[0])
        args = argv[1:]
        if any(a in ("-t", "--target-directory") or a.startswith("--target-directory=") for a in args):
            return  # a directory target (`cp -t DIR ...`, T061) keeps the source's basename: judged by name
        value_opts = {"cp": ("-S", "--suffix"), "mv": ("-S",), "install": ("-m", "-o", "-g", "-S"),
                      "ln": ("-S",)}[name]
        pos = cmds.positionals(args, value_opts)
        if len(pos) != 2:
            return
        source, target = args[pos[0]], args[pos[1]]
        normal = self.policy.normalize(target, self.cwd)
        if normal is not None and UNRESOLVED not in source:
            self.aliases[normal] = cmds.name_of(source)

    def program_identity(self, path_text, alias, args, raw):
        """Command rules for the real identity of an executed file (T057, R008 #12): the basename of an interpreted
        file or the source basename of an alias is the command name; a path through a `claude-code`/spawn directory
        is `cmd-spawn-agent`."""
        before = len(self.hits)
        pseudo = alias if alias is not None else cmds.name_of(path_text)
        if pseudo:
            self._command_rules([pseudo] + list(args), raw, pseudo)
        if not any(rule == "cmd-spawn-agent" for rule, _ in self.hits[before:]):
            for part in path_text.split("/"):
                if part in rules.SPAWN_COMMANDS or "claude-code" in part:
                    self.add("cmd-spawn-agent", raw, part)
                    break
        return len(self.hits) > before  # True when the file's real identity broke a rule

    def _command_rules(self, argv, raw, name):
        args = argv[1:]
        if name in rules.GH_COMMANDS:
            self.add("cmd-gh", raw, name)
        if name in rules.SPAWN_COMMANDS:
            self.add("cmd-spawn-agent", raw, name)
        if "--no-verify" in args:
            self.add("cmd-no-verify", raw, "--no-verify")
        if name == "ssh-add":
            self.add("read-ssh-material", raw, name)  # lists or loads the agent's keys (T057, R008 #9)
        if name.startswith("git-credential"):
            self.add("cmd-git-credential", raw, name)
        if name == "git":
            self._note_git_add(argv)
            argv = self.effective_git_argv(argv, self.cmd_env)  # GIT_CONFIG_*, --config-env are `-c` (T057)
            found = cmds.git_hits(argv)
            if "git-config-override" in found and self.local_submodule(argv):
                found = [rule for rule in found if rule != "git-config-override"]  # T077
            self.git_taint(argv, found)
            for rule in found:
                if rule != "cmd-git-main" or not self.git_in_own_clone(argv):
                    self.add(rule, raw, "git")
            if cmds.git_is_networked(argv) and not (cmds.git_remote_ok(argv) or self.git_local_remote(argv)):
                self.add("cmd-git-network", raw, "git")
        if name in ("cp", "ln", "install", "mv"):
            self._note_alias(argv)
        if cmds.install_hit(argv):
            self.add("cmd-install", raw, name)
        if cmds.env_dump(argv):
            self.add("cmd-env-dump", raw, name)
        if cmds.network_hit(argv):
            self.add("cmd-network", raw, name)

    @staticmethod
    def _data_indexes(argv, name, shell_sink):
        skip = set()
        if name in ("echo", "printf") and not shell_sink:
            skip.update(range(1, len(argv)))
        if name == "eval":
            skip.update(range(1, len(argv)))
        elif name in rules.INTERPRETERS or cmds.interpreter_kind(name) is not None:
            at = cmds.code_word(name, argv[1:])[0]
            if at is not None:
                skip.add(at + 1)  # the inline code is audited as code, not read as a path
        if name in ("grep", "egrep", "fgrep", "rg", "ag", "ack"):
            skip.update(_grep_pattern_indexes(argv))
        if name == "git":
            for i, arg in enumerate(argv[:-1]):
                if arg in _DATA_SKIP_OPTS or re.fullmatch(r"-[a-zA-Z]*m", arg):
                    skip.add(i + 1)
            skip.update(i for i, arg in enumerate(argv) if arg.startswith("--message=") or
                        re.fullmatch(r"-[a-zA-Z]+m.+", arg))
        return skip

    # -- assignment values (T057, R008 #10) -------------------------------------------------------
    def _assignment_values(self, item, raw, depth, env):
        """Every value a program can consume: `NAME=value CMD`, `env NAME=value`, `export`/`declare`/`local NAME=value`
        (a bare `NAME=value` is a shell variable: judged where it is used). Each is read-checked as a path list
        (`PYTHONPATH=a:b`, `GIT_DIR=...`, `BASH_ENV=...`); the value of a variable a program runs as a command
        (`*_PAGER`, `*_EDITOR`, `GIT_SSH_COMMAND`, ...) is audited as shell. The prefix values of a `tools/job run` CMD
        are audited once, on the tools/job item."""
        prefix = item.prefix_values if item.argv and not item.wrapped else []
        pairs = prefix + item.env_values
        if item.argv and cmds.name_of(item.argv[0]) in _DECLARERS:
            pairs += list(_declared(item.argv[1:]).items())
        for name, value in pairs:
            if _COMMAND_VAR_RE.match(name) and value.strip():
                self.bash(value, depth + 1, env)
            if name == "PS4" and value.strip():  # PS4 is re-expanded at use (set -x); its $(...) run (R008 #11)
                for sub in shell.body_expansions(value)[0]:
                    self.bash(sub, depth + 1, env)
            self.value_reads(value, raw)

    # -- command strings run by wrappers and builtins (T057, R008 #11) ------------------------------
    def _command_strings(self, item, argv, name, raw, depth, env):
        """A command handed as a string to a wrapper or builtin runs as shell: `script -c`, `flock -c`, `su -c`,
        `trap HANDLER`, `parallel`, awk `system("...")` and sed `e command`. (coproc is a keyword, already
        stripped; git rebase -x / bisect run / submodule foreach are in git_exec_strings.)"""
        args = argv[1:]
        if item.wrapped:
            return
        if name in ("script", "flock", "su"):
            code = cmds.opt_value(args, ("-c", "--command"))
            if code is not None:
                self.bash(code, depth + 1, env)
        elif name == "trap" and args and args[0] not in ("-", "", "-p", "-l", "--"):
            self.bash(args[0], depth + 1, env)
        elif name == "parallel":
            for code in cmds.parallel_commands(args):
                if code.strip():
                    self.bash(code, depth + 1, env)
        elif name in _AWK_NAMES:
            for code in cmds.awk_system_calls(argv):
                self.bash(code, depth + 1, env)
        elif name in _SED_NAMES:
            for code in cmds.sed_exec_commands(argv):
                self.bash(code, depth + 1, env)

    def _program_texts(self, argv, name, raw):
        """An awk or sed program is code (T062, R008 #19): the forbidden fragments are searched in its whole text
        (`getline < "FILE"`), whether or not it looks like code; sed's `r`/`R FILE` reads FILE and `w`/`W FILE`
        writes it; and awk's `ENVIRON` without a subscript (`for (k in ENVIRON)`) is the whole environment."""
        programs = cmds.awk_programs(argv) if name in _AWK_NAMES else (
            cmds.sed_scripts(argv) if name in _SED_NAMES else [])
        for letter, path_text in cmds.sed_file_commands(argv) if name in _SED_NAMES else ():
            if letter in "rR":
                self.read_word(path_text, raw, name, force=True)
            else:  # `w FILE` writes it, even under -n
                self.write(path_text, "rewrite", raw)
        for program in programs:
            self.scan_fragments(program, raw)
            match = _AWK_ENVIRON_RE.search(program) if name in _AWK_NAMES and not self.clean_env else None
            if match is not None:
                self.add("cmd-env-dump", raw, match.group(0))

    def value_reads(self, value, raw):
        """Read-check a value that names paths (a `:`-separated list), without counting it as a read of a file."""
        if is_url(value):
            return
        saved = set(self.read_set)
        for piece in value.split(":") if ":" in value else [value]:
            if piece:
                self.read_word(piece, raw, "")
        self.read_set = saved

    # -- reads -------------------------------------------------------------------------------
    def _read_words(self, item, argv, raw, name, skip):
        dirs = cmds.arg_dirs(name, argv, self.cwd, self.policy.normalize)
        for index, word in enumerate(argv):
            if index in skip or (index == 0 and "/" not in word):
                continue
            if dirs is not None:
                self.cwd = dirs[index]  # after `-C DIR` (tar, make, git) the arguments resolve in DIR
            if UNRESOLVED in self.cwd and index and name in _READERS and "/" not in word and not \
                    word.startswith(("-", "~", ".", UNRESOLVED)):
                self._unknown_cwd_read(word, raw, name, None)  # `ls T042` with the directory unknown
                continue
            self.read_word(word, raw, name)
        self.cwd = item.cwd
        for redirect in [] if item.wrapped else item.cmd.redirects:
            if redirect.op in ("<", "<>"):
                self.read_word(self.expand(redirect.target, self.env_now), raw, name)

    def _recursive_reads(self, argv, raw, name):
        """Rule T052 (R008 #7): a recursive reader rooted at a directory that holds a forbidden root."""
        roots = cmds.recursive_roots(name, argv)
        if roots is None:
            return
        dirs = cmds.arg_dirs(name, argv, self.cwd, self.policy.normalize)
        texts = [(argv[i], dirs[i] if dirs else self.cwd) for i in roots if i < len(argv)] or [(".", self.cwd)]
        for text, cwd in texts:
            self.recursive_root(text, cwd, raw)

    def recursive_root(self, text, cwd, raw):
        """Check one root of a recursive read. A wildcard root is the directory above its first wildcard component,
        an unknown piece is left out (`/var/tmp/$X` descends from /var/tmp at least); an unknown working directory or
        a path-leading unknown piece is left to the plain read (path-unresolved)."""
        if is_url(text) or text.startswith(UNRESOLVED) or re.match(r"[\w.-]+@?[\w.-]*:", text):
            return
        parts = text.replace(UNRESOLVED, "").split("/")
        for index, part in enumerate(parts):
            if re.search(r"[*?\[]", part):
                parts = parts[:index]
                break
        base = "/".join(parts) or ("/" if text.startswith("/") else ".")
        for variant in expand_braces(base):
            normal = self.policy.normalize(variant, cwd)
            rule = self.policy.recursive_rule(normal) if normal is not None else None
            if rule is not None:
                token = text.replace(UNRESOLVED, "$(")
                if (rule, excerpt_around(raw, token)) not in self.hits:
                    self.add(rule, raw, token)
                return

    def socket_path(self, text, raw):
        """Rule `cmd-network` for bash's `/dev/tcp/HOST/PORT` and `/dev/udp/...` (T060, R008 #15): a redirect or path
        argument there opens a connection. An unknown host, or one not on the allowlist (loopback is fine, as for the
        network tools), is `cmd-network`."""
        normal = self.policy.normalize(text, self.cwd) if UNRESOLVED not in text else None
        host = cmds.socket_host(normal if normal is not None else text)
        if host is not None and (UNRESOLVED in host or not cmds.host_allowed(host)):
            self.add("cmd-network", raw, text.replace(UNRESOLVED, "$("))
        return host is not None

    def read_word(self, text, raw, name="", force=False):
        self.socket_path(text, raw)
        if is_url(text):
            self._url_forbidden(text, raw)  # hidden-repo / clean-room checks on a URL path (T057, R008 #14)
        candidates = [text]
        eq = re.match(r"(?:-[^=\s]*|of|if|file|path)=(.*)\Z", text, re.DOTALL)
        if eq is not None and not text.startswith(_NON_PATH_OPTS):
            candidates.append(eq.group(1))
        attached = _ATTACHED_RE.match(text)  # `-C/path`, `-I/path`, `@file` (T052, R008 #5)
        if attached is not None:
            candidates.append(attached.group(1))
        for candidate in candidates:
            for variant in expand_braces(candidate):
                self._read_candidate(variant, raw, name, force)
        if _CODE_LIKE.search(text):
            self.scan_fragments(text, raw)

    def _url_forbidden(self, text, raw):
        """A URL whose host or path names a `*-hidden` repo or `annas-mcp` (clean room) is a forbidden fetch."""
        from urllib.parse import urlsplit
        parts = urlsplit(text)
        probe = "/" + (parts.hostname or "") + (parts.path or "")
        for pattern, rule in _FRAGMENTS:
            if rule in ("read-hidden-repo", "read-clean-room"):
                match = pattern.search(probe)
                if match is not None:
                    self.add(rule, raw, match.group(0).strip(" '\"=:/"))

    def _read_candidate(self, text, raw, name, force=False):
        if text.startswith(UNRESOLVED) and name in _READERS and not force:
            self.add("path-unresolved", raw, text.replace(UNRESOLVED, "$("))
            return
        if is_url(text) or not (force or "/" in text or text.startswith(("~", "."))):
            return
        if text.startswith("file://"):
            text = text[len("file://"):]
        if UNRESOLVED in text:
            if self._unknown_piece_rule(text, raw):
                return
            prefix = text.split(UNRESOLVED)[0]
            if prefix.startswith("/") and prefix.endswith("/") and len(prefix) > 1:
                self._read_rule(self.policy.normalize(prefix, self.cwd), raw, text)
            elif name in _READERS and (prefix == "" or prefix == "~"):
                self.add("path-unresolved", raw, text.replace(UNRESOLVED, "$("))
            return
        normal = self.policy.normalize(text, self.cwd)
        if normal is None:
            if UNRESOLVED in self.cwd and not text.startswith(("/", "~")):
                self._unknown_cwd_read(text, raw, name, force)
            return
        self.read_set.add(normal)
        rule = self.policy.read_rule(normal) or self.policy.glob_rule(text, self.cwd)
        if rule is not None:
            self.add(rule, raw, text)

    def _unknown_cwd_read(self, text, raw, name, force):
        """A relative path while the working directory is unknown: a block when its first component is a
        forbidden name (another task's id dir, `.config`, `.claude*`, `.ssh`), else path-unresolved for readers."""
        first = text.split("/", 1)[0]
        for pattern, rule in _UNKNOWN_CWD_FIRST:
            if pattern.match(first) and first != self.task.task_id:
                self.add(rule, raw, text)
                return
        if force is not None and (name in _READERS or force):
            self.add("path-unresolved", raw, "$(cwd)/" + text)

    def _unknown_piece_rule(self, text, raw):
        """Rule of a path with unknown pieces (T052, R008 #5): each piece replaced by "" and by "*"; the first
        variant that hits a forbidden root decides (block). True when one did."""
        shown = text.replace(UNRESOLVED, "$(")
        for fill in ("", "*"):
            variant = text.replace(UNRESOLVED, fill)
            if not variant.startswith(("/", "~")):
                continue  # a path-leading unknown piece: the directory is unknown (path-unresolved), see below
            normal = self.policy.normalize(variant, self.cwd)
            rule = None if normal is None else self.policy.read_rule(normal) or self.policy.glob_rule(variant, self.cwd)
            if rule is not None:
                self.add(rule, raw, shown)
                return True
        return False

    def _read_rule(self, normal, raw, token):
        rule = self.policy.read_rule(normal) if normal else None
        if rule is not None:
            self.add(rule, raw, token)

    def scan_fragments(self, text, raw):
        for exempt in self.policy.exempt:  # an announced file, spelled exactly and standing alone
            text = re.sub(r"(?<![\w./-])" + re.escape(exempt) + r"(?![\w./-])", "", text)
        for pattern, rule in _FRAGMENTS:
            match = pattern.search(text)
            if match is not None:
                self.add(rule, raw, match.group(0).strip(" '\"=:"))
        for pattern in _PATH_FRAGMENTS:  # another task's cache or worktree named inside the text (T062, R008 #19)
            for match in pattern.finditer(text):
                normal = self.policy.normalize(match.group(0), self.cwd)
                rule = self.policy.read_rule(normal) if normal else None
                if rule in _PATH_FRAGMENT_RULES:
                    self.add(rule, raw, match.group(0))
                    break

    # -- secrets -----------------------------------------------------------------------------
    def _secret_words(self, argv, raw, name, skip):
        accessor = name in ("printenv", "env", "export", "unset", "declare", "typeset")
        for index, word in enumerate(argv[1:], start=1):
            if index in skip:
                continue
            for match in rules.SECRET_NAME_RE.finditer(word):
                exact = match.group(0) == word.split("=", 1)[0] and "=" not in word
                if accessor and exact and name in ("printenv", "env"):
                    self.add("secret-env-access", raw, match.group(0))
                else:
                    self.add("secret-env-mention", raw, match.group(0))

    # -- writes ------------------------------------------------------------------------------
    def _write_targets(self, item, argv, raw):
        """Write every file the command names. A copy, move, install or link into a directory (`-t DIR`,
        `--target-directory=DIR`, several sources, or a target that is `.`, ends in `/` or is a known directory)
        writes `DIR/basename(source)` for each source (T061, R008 #17)."""
        indexes = set()
        layout = writers.transfer(argv)
        carried = self._carried_texts(argv, layout)
        if layout is not None and not (layout["dir"] or self.is_dir(layout["text"], layout.get("follow", True))):
            layout = None
        self.delete_recursive = writers.recursive_delete(argv)
        for index, op, text in writers.write_targets(argv):
            if index < len(argv):
                indexes.add(index)
                if layout is not None and index == layout["target"] and UNRESOLVED not in text:
                    for source in layout["sources"]:
                        self.write(writers.into_dir(text, argv[source]), op, raw)
                        self._carry(carried.get(source), writers.into_dir(text, argv[source]))
                    continue
                self.write(re.sub(r"\Aof=", "", text), op, raw)
                if carried and op == "rewrite":
                    self._carry(next(iter(carried.values())) if len(carried) == 1 else None, text)
        if layout is not None and layout["target"] is None:  # `ln -s TARGET` links ./basename(TARGET)
            self.write(writers.into_dir(".", argv[layout["sources"][0]]), "rewrite", raw)
        self.delete_recursive = True  # any other writer of a delete is judged as able to remove a tree
        if cmds.name_of(argv[0]) == "mkdir":
            self.dirs.update(n for n in (self.policy.normalize(argv[i], self.cwd) for i in indexes) if n)
        return indexes

    def _carried_texts(self, argv, layout):
        """{argv index of a source: (text, dirty)} for the sources of `cp`/`mv`/`install` whose text the audit knows:
        the copy has the same text (T061; a copy of the agent's own script run in a scratch dir is audited as code)."""
        if layout is None or cmds.name_of(argv[0]) not in ("cp", "mv", "install"):
            return {}
        found = {}
        for index in layout["sources"]:
            normal = self.policy.normalize(argv[index], self.cwd)
            if normal is not None and normal in self.files and normal not in self.unknown:
                found[index] = (self.files[normal], normal in self.dirty)
        return found

    def _carry(self, known, target):
        normal = self.policy.normalize(target, self.cwd)
        if known is None or normal is None:
            return
        self.record_file(normal, known[0])
        if known[1]:
            self.dirty.add(normal)

    def is_dir(self, text, follow=True):
        """True when a copy target is a directory: `.`, `..`, a trailing `/`, the working directory or one of the
        agent's roots, a directory the transcript made or wrote files into, or a directory on the disk; with `follow`,
        also through a link the transcript made."""
        if text in (".", "..") or text.endswith(("/", "/.", "/..")):
            return True
        normal = self.policy.normalize(text, self.cwd)
        if normal is None:
            return False
        normal = (self.policy.through_links(normal) or normal) if follow else normal  # a link made in the transcript
        if normal == self.cwd or normal in self.policy.own or normal in self.dirs:
            return True
        inside = normal.rstrip("/") + "/"
        if any(f.startswith(inside) for f in self.files) or any(f.startswith(inside) for f in self.created):
            return True
        return os.path.isdir(self.policy.real(normal)) if follow else os.path.isdir(normal) and not os.path.islink(normal)

    def _redirect(self, command, redirect):
        if redirect.op in ("<", "<<", "<<-", "<<<", "<&"):
            return
        target = self.expand(redirect.target, self.env_now)
        if redirect.op == ">&" and (target.isdigit() or target == "-"):
            return
        op = "edit" if redirect.op in (">>", "&>>") else "rewrite"
        self.write(target, op, command.raw)
        if redirect.fd not in (None, "1") or redirect.op not in (">", ">>", ">|"):
            return  # stderr only, or `&>`: what lands in the file is not (only) the text below
        name = cmds.name_of(command.words[0].text if command.words else "")
        if command.heredocs and name in ("cat", "tee") and known_body(command.heredocs[0]):
            self.keep_text(target, op, command.heredocs[0].body)

    def keep_text(self, target, op, body):
        """Remember the text a here-document wrote to `target`, so a later run of the file can be audited.
        An append extends what is known; an append to a file whose content is unknown leaves it unknown."""
        normal = self.policy.normalize(target, self.cwd) if UNRESOLVED not in target else None
        if normal is None:
            return
        if op == "rewrite":
            self.record_file(normal, body)
        elif self.known_before == normal:
            self.files[normal] += "\n" + body
            self.dirty.discard(normal)

    def write(self, text, op, raw):
        if self.socket_path(text, raw):
            return  # a socket, not a file: judged as network only
        if UNRESOLVED in text:
            self._unresolved_write(text, raw)
            return
        normal = self.policy.normalize(text, self.cwd)
        if normal is None:
            self.add("write-unresolved", raw, text)
            return
        self.git_touch(normal)
        self.forget_output(normal)
        self.known_before = normal if normal in self.files and normal not in self.dirty else None
        self._content_changed(normal, op)
        landed = self.policy.through_links(normal, follow_last=op != "delete" or text.endswith("/"))
        if op == "delete" and not text.endswith("/"):
            self.policy.drop_links(normal)  # `rm LINK` removes the link, not what it points at
        if landed is None:  # through a link whose target the audit does not know (T061, R008 #18)
            self.add("write-unresolved", raw, text)
            return
        if not self.policy.write_ok(landed):
            self.add("write-outside", raw, text)
            return
        self.tamper_check(landed, "rewrite" if op == "build" else op, raw, text)

    def _content_changed(self, normal, op):
        """What the audit knows of a file's text after a write (T049, R008 #3). A rewrite replaces it with text
        the audit does not know (a redirect of command output, `cp`, `base64 -d >`, `tee` in a pipe, `mv`), until
        a writer whose text is known records it right after (Write, literal `echo`/`printf >`, a quoted
        here-document). An edit of a known file makes it `dirty` (audited as written, reviewed); a deleted file
        is forgotten."""
        if op in ("delete", "build"):  # a compiler's output is a program, not a text to audit (T061)
            self.files.pop(normal, None)
            self.dirty.discard(normal)
            self.unknown.discard(normal)
        elif op == "rewrite":
            if normal in self.files:
                self.dirty.add(normal)
            self.unknown.add(normal)
        elif op == "edit" and normal in self.files:
            self.dirty.add(normal)

    def _unresolved_write(self, text, raw):
        """A write target with an unknown part. When the unknown part is one final path component, the
        directory above it is known: outside the allowed places it is `write-outside`; in a declared
        scratch directory nothing can matter (no protected or test files there); in the worktree a human
        must look, because the component could be a protected or test file."""
        shown = text.replace(UNRESOLVED, "$(")
        cut = text.split(UNRESOLVED)[0]
        if not cut.startswith("/") or "/" in text[len(cut):]:
            self.add("write-unresolved", raw, shown)
            return
        directory = self.policy.normalize(cut[:cut.rindex("/") + 1], self.cwd)
        if directory is None or self.policy.relative_to_worktree(directory) is not None:
            self.add("write-unresolved", raw, shown)
        elif not self.policy.write_ok(directory):
            self.add("write-outside", raw, shown)

    def tamper_check(self, normal, op, raw, token):
        rel = self.policy.relative_to_worktree(normal)
        if rel is None:
            return
        task = self.task
        probes = [rel, rel + "/x"] if op == "delete" else [rel]  # deleting a directory deletes below it
        if any(task.is_protected(p) for p in probes):
            self.add("tamper-protected", raw, token)
        elif not any(task.is_allowed(p) for p in probes):
            self.add("write-not-allowed", raw, token)
        if task.implementer and any(task.is_test(p) for p in probes):
            made = normal in self.created
            if op == "delete" and not made:
                # `rm dir/*.orig` removes patch leftovers, unless it can remove a directory with tests (T077, B26)
                if self.delete_recursive or not writers.patch_leftover_glob(rel):
                    self.add("tamper-test-delete", raw, token)
            elif op == "rewrite" and normal in self.read_set and not made:
                self.add("tamper-test-rewrite", raw, token)
            elif op == "edit" and not made:
                self.add("test-edit", raw, token)
        if op == "delete":
            self.created.discard(normal)
        elif normal not in self.read_set:
            self.created.add(normal)


def known_body(doc):
    """True when the text a here-document writes is known: a quoted delimiter, or an unquoted body that
    expands nothing."""
    return doc.quoted or shell.body_is_literal(doc.body)


def _grep_pattern_indexes(argv):
    """The search pattern of grep-like commands is text, not a path."""
    found, explicit = set(), False
    for i, arg in enumerate(argv[1:-1], start=1):
        if arg in ("-e", "--regexp", "-f", "--file"):
            found.add(i + 1)
            explicit = True
    if not explicit:
        plain = cmds.positionals(argv[1:], ("-A", "-B", "-C", "-m", "-g", "--glob", "-t", "--type", "--include",
                                            "--exclude", "--exclude-dir", "-d", "-D", "--max-count"))
        if plain:
            found.add(plain[0] + 1)
    return found
