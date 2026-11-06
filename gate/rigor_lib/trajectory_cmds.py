"""Command-specific rules of `rigor trajectory`: pure functions over an expanded argv."""

import posixpath
import re
from urllib.parse import urlsplit

from rigor_lib import trajectory_rules as rules
from rigor_lib.trajectory_shell import UNRESOLVED

KEYWORDS = ("{", "}", "!", "then", "do", "else", "if", "while", "until", "fi", "done", "elif", "for", "case",
            "esac", "function", "select")
_ASSIGN_WORD = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
_HOST_RE = re.compile(r"\A(?:[\w-]+@)?(?P<host>\[[0-9a-fA-F:]+\]|[A-Za-z0-9_.-]+)(?::\d+)?(?:[:/].*)?\Z")
_CURL_VALUE_OPTS = ("-o", "-H", "-d", "-X", "-u", "-A", "-e", "-K", "-T", "-w", "-m", "-x", "-b", "-c", "-F",
                    "--output", "--header", "--data", "--data-raw", "--data-binary", "--request", "--user",
                    "--user-agent", "--max-time", "--proxy", "--cacert", "--cert", "--key", "--form",
                    "-O", "-P", "--output-dir", "-t", "-T", "--limit-rate", "-w")
_CLUSTER_N = re.compile(r"\A-[a-zA-Z]*n[a-zA-Z]*\Z")


def name_of(word):
    return posixpath.basename(word) if word else ""


def positionals(args, value_opts=()):
    """Indexes of the non-option arguments (`--` ends options; value_opts take the next word)."""
    found, i, plain = [], 0, False
    while i < len(args):
        arg = args[i]
        if not plain and arg == "--":
            plain = True
        elif not plain and arg.startswith("-") and arg != "-":
            if arg in value_opts:
                i += 1
        else:
            found.append(i)
        i += 1
    return found


# -- interpreters: where the code is (T049, R008 #2) ------------------------------------------
class _Flags:
    __slots__ = ("code", "valued", "attached", "stop", "long_code", "long_valued")

    def __init__(self, code, valued="", attached="", stop="", long_code=(), long_valued=()):
        self.code = code                # short letters that take the code (alone or inside a cluster)
        self.valued = valued            # short letters whose value is the rest of the cluster, else the next word
        self.attached = attached        # short letters whose (optional) value can only be attached
        self.stop = stop                # short letters after which options end (`python -m mod`)
        self.long_code = long_code      # long code flags (`--eval CODE`, `--eval=CODE`)
        self.long_valued = long_valued  # long options that take the next word


_CODE_FLAGS = {
    "shell": _Flags("c", valued="oO", long_valued=("--rcfile", "--init-file")),
    "python": _Flags("c", valued="WX", stop="m"),
    "node": _Flags("ep", valued="r", long_code=("--eval", "--print"),
                   long_valued=("--require", "--import", "--loader", "--input-type", "--env-file")),
    "perl": _Flags("eE", attached="IMmxil0CdDV"),
    "ruby": _Flags("e", valued="IrCE", attached="x0lFKTW"),
    "php": _Flags("r", valued="dcfz"),
    "lua": _Flags("e", valued="l"),
}
STDIN_PATHS = ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")


def interpreter_kind(name):
    if name in rules.SHELLS:
        return "shell"
    if re.fullmatch(r"python[0-9.]*", name):
        return "python"
    return name if name in _CODE_FLAGS else None


def _cluster(flags, arg):
    """('code', attached code or None) | ('value', True when the next word is the value) | ('stop', _) |
    ('plain', _) for one single-dash (or `+`) option word."""
    body = arg[1:]
    for k, char in enumerate(body):
        rest = body[k + 1:]
        if char in flags.code:
            return "code", (rest if rest and arg[0] == "-" and flags is not _CODE_FLAGS["shell"] else None)
        if char in flags.valued:
            return "value", rest == ""
        if char in flags.attached:
            return "value", False
        if char in flags.stop:
            return "stop", rest == ""
    return "plain", False


def code_word(name, args):
    """(index into args of the inline code, True when a code flag was given) for an interpreter command.

    The code flag comes from the interpreter's table: a short flag alone (`-c`) or inside a cluster (`-ec`,
    `-ne`), or a long one (`--eval`). The code is the first plain word after it, skipping other options, the
    values of options that take one, and `--`; `-cCODE` and `--eval=CODE` carry it in the same word (the index of
    that word; attached_code() cuts it out). (None, False): no code flag (a script file, stdin, `-m`);
    (None, True): a code flag with no code after it."""
    kind = interpreter_kind(name)
    if kind is None:
        return None, False
    flags = _CODE_FLAGS[kind]
    i, flagged = 0, False
    while i < len(args):
        arg = args[i]
        if arg == "--":
            if flagged and i + 1 < len(args):
                return i + 1, True
            return None, flagged
        if arg == "-" or not arg.startswith(("-", "+")) or (arg[0] == "+" and kind != "shell"):
            return (i, True) if flagged else (None, False)
        if arg.startswith("--"):
            key = arg.split("=", 1)[0]
            if key in flags.long_code:
                if "=" in arg:
                    return i, True
                flagged = True
            elif arg in flags.long_valued:
                i += 1
        else:
            what, extra = _cluster(flags, arg)
            if what == "code":
                if extra:
                    return i, True
                flagged = True
            elif what == "value" and extra:
                i += 1
            elif what == "stop":
                return None, flagged
        i += 1
    return None, flagged


def attached_code(name, word):
    """The code text of the word code_word() pointed at (`-cCODE`, `--eval=CODE`, or a plain word)."""
    kind = interpreter_kind(name)
    if kind is None or word == "-" or not word.startswith("-"):
        return word
    if word.startswith("--"):
        return word.split("=", 1)[1] if "=" in word else word
    what, extra = _cluster(_CODE_FLAGS[kind], word)
    return extra if what == "code" and extra else word


# -- wrappers --------------------------------------------------------------------------------
def _skip_options(argv, start, with_value):
    i = start
    while i < len(argv) and argv[i].startswith("-") and argv[i] != "-":
        if argv[i] == "--":
            return i + 1
        i += 2 if argv[i] in with_value else 1
    return i


def unwrap_once(argv):
    """(inner argv, extra rule ids) for a wrapper command (inner may be empty); (None, []) if not one."""
    name = name_of(argv[0])
    extra = []
    if name == "env":
        i = 1
        while i < len(argv):
            arg = argv[i]
            if arg == "--":
                i += 1
                break
            if arg in ("-u", "-C", "-S", "--unset", "--chdir", "--split-string"):
                i += 2
            elif arg.startswith("-") or _ASSIGN_WORD.match(arg):
                i += 1
            else:
                break
        return argv[i:], (["cmd-env-dump"] if i >= len(argv) else [])
    table = {
        "command": (), "builtin": (), "exec": ("-a",), "nohup": (), "time": ("-f", "-o"), "setsid": (),
        "nice": ("-n",), "ionice": ("-c", "-n", "-p"), "stdbuf": ("-i", "-o", "-e"), "sudo": (
            "-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"), "doas": ("-u", "-C"),
        "xargs": ("-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "-J"), "timeout": ("-k", "-s", "--signal",
                                                                                   "--kill-after"),
        "flock": ("-w", "-E"), "watch": ("-n", "-d"),
    }
    if name not in table:
        return None, []
    if name == "command" and any(a in ("-v", "-V") for a in argv[1:3]):
        return [], []  # `command -v gh` only looks the name up
    if name in rules.SUDO_COMMANDS:
        extra.append("cmd-sudo")
    i = _skip_options(argv, 1, table[name])
    if name in ("timeout", "flock", "watch") and i < len(argv):
        i += 1  # duration / lock file
    return argv[i:], extra


def env_wrappers(prefix):
    """(assignments, clean) given by the `env` wrappers in the words stripped in front of a command:
    {NAME: value} of `env NAME=value ...` and whether `env -i` emptied the inherited environment (the
    assignments after it are then the whole environment). Later words win."""
    assigns, clean, i = {}, False, 0
    while i < len(prefix):
        if name_of(prefix[i]) != "env":
            i += 1
            continue
        i += 1
        while i < len(prefix):
            arg = prefix[i]
            if arg in ("-i", "--ignore-environment", "-"):
                assigns, clean = {}, True
            elif arg in ("-u", "-C", "-S", "--unset", "--chdir", "--split-string"):
                i += 1
            elif _ASSIGN_WORD.match(arg):
                key, _, value = arg.partition("=")
                assigns[key] = value
            elif not arg.startswith("-"):
                break
            i += 1
    return assigns, clean


def env_chdir(prefix):
    """The directory of `env -C DIR` / `env --chdir=DIR` among the wrappers stripped in front of a command, or None."""
    found, i = None, 0
    while i < len(prefix):
        if name_of(prefix[i]) == "env":
            j = i + 1
            while j < len(prefix) and prefix[j].startswith("-"):
                arg = prefix[j]
                if arg in ("-C", "--chdir") and j + 1 < len(prefix):
                    found = prefix[j + 1]
                    j += 1
                elif arg.startswith("--chdir="):
                    found = arg[len("--chdir="):]
                elif arg.startswith("-C") and len(arg) > 2:
                    found = arg[2:]
                elif arg in ("-u", "-S", "--unset", "--split-string"):
                    j += 1
                j += 1
            i = j
        else:
            i += 1
    return found


_CHDIR_OPTS = {"tar": ("-C", "--directory"), "make": ("-C", "--directory"), "gmake": ("-C", "--directory"),
               "git": ("-C",)}


def arg_dirs(name, argv, cwd, normalize):
    """The directory each argument of `tar`/`make`/`git` is resolved in: a `-C DIR` (`-CDIR`, `--directory=DIR`)
    applies to the arguments after it (T052, R008 #6). None for other commands."""
    opts = _CHDIR_OPTS.get(name)
    if opts is None:
        return None
    dirs, here, i = [], cwd, 0
    while i < len(argv):
        arg, value, skip = argv[i], None, False
        if i > 0 and arg in opts and i + 1 < len(argv):
            value, skip = argv[i + 1], True
        elif i > 0 and "-C" in opts and arg.startswith("-C") and len(arg) > 2:
            value = arg[2:]
        elif i > 0 and arg.startswith("--directory=") and "--directory" in opts:
            value = arg[len("--directory="):]
        dirs.append(here)
        if skip:
            dirs.append(here)
            i += 1
        if value is not None:
            here = normalize(value, here) or UNRESOLVED
        i += 1
    return dirs


def clean_environment(assigns, clean):
    """True when `env -i` left an environment without a secret-looking variable name: not an env dump."""
    return clean and not any(rules.SECRET_NAME_RE.search(name) for name in assigns)


def kill_targets(argv):
    """The process ids/job specs a `kill` command names (options and signal names removed); None for
    `kill -l` (lists signal names) and `kill -0` (tests existence) signal nothing."""
    found, i, plain = [], 1, False
    while i < len(argv):
        arg = argv[i]
        if not plain and arg == "--":
            plain = True
        elif not plain and arg in ("-s", "-n", "-q", "--signal", "--queue"):
            i += 1
        elif not plain and arg in ("-l", "-L", "--list", "--table"):
            return None
        elif not plain and arg in ("-0", "-s0", "-n0"):
            return None  # signal 0 only tests whether the process exists
        elif plain or not arg.startswith("-"):
            found.append(arg)
        i += 1
    return found


def job_run(argv):
    """(index of the `--dir` value word or None, index of the `--`) for `tools/job run ... -- CMD`, else None.

    Mirrors parse_run in tools/job: options and NAME come before the first `--` that is not an option's
    value; CMD (non-empty) follows it. `wait`, `status` and `list` run nothing and are not wrappers."""
    if name_of(argv[0]) != "job" or argv[1:2] != ["run"]:
        return None
    i, directory = 2, None
    while i < len(argv) and argv[i] != "--":
        if argv[i] in ("--deadline", "--dir"):
            directory = i + 1 if argv[i] == "--dir" else directory
            i += 2
            continue
        if argv[i].startswith("--dir="):
            directory = i
        i += 1
    if i + 1 >= len(argv):
        return None
    return directory, i


# -- git -------------------------------------------------------------------------------------
def git_parts(argv):
    """(config overrides, subcommand, sub-args) for a git argv."""
    i, confs = 1, []
    while i < len(argv) and argv[i].startswith("-"):
        arg = argv[i]
        if arg == "-c" and i + 1 < len(argv):
            confs.append(argv[i + 1])
            i += 2
        elif arg in ("-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                     "--super-prefix"):
            i += 2
        else:
            i += 1
    return confs, (argv[i] if i < len(argv) else ""), argv[i + 1:]


def _is_main_ref(word):
    return re.fullmatch(r"(?:\+)?(?:refs/heads/|refs/remotes/[^/]+/|origin/|upstream/)?(?:main|master)"
                        r"(?:[~^@]\S*)?", word) is not None


def _git_config_hits(sub_args):
    flags = [a for a in sub_args if a.startswith("-")]
    plain = [a for a in sub_args if not a.startswith("-")]
    if any(f in rules.GIT_CONFIG_WRITE_FLAGS for f in flags):
        return ["cmd-git-config-write"]
    if any(f in rules.GIT_CONFIG_READ_FLAGS for f in flags):
        return []
    return ["cmd-git-config-write"] if len(plain) >= 2 else []


def _git_main_hits(sub, sub_args):
    flags = [a for a in sub_args if a.startswith("-")]
    if sub == "branch" and any(f in rules.GIT_BRANCH_READ_FLAGS for f in flags):
        return []
    if sub in rules.GIT_MAIN_SUBS and any(_is_main_ref(a) for a in sub_args):
        return ["cmd-git-main"]
    return []


def git_hits(argv):
    """Rule ids for one git command (excluding network, handled by git_remote_urls)."""
    confs, sub, sub_args = git_parts(argv)
    found = []
    for conf in confs:
        key = conf.split("=", 1)[0].lower()
        if key == "core.hookspath":
            found.append("cmd-no-verify")
        elif key not in rules.GIT_ALLOWED_C_KEYS:
            found.append("git-config-override")
    if sub in ("push", "send-pack", "http-push") or (sub == "lfs" and sub_args[:1] == ["push"]):
        found.append("cmd-git-push")  # send-pack and http-push are push plumbing (T057, R008 #9)
    if (sub == "credential" and sub_args[:1] != ["capability"]) or sub.startswith("credential-"):
        found.append("cmd-git-credential")
    if sub in ("commit", "merge", "push", "am", "rebase", "cherry-pick", "revert") and any(
            a == "--no-verify" or (sub in ("commit", "merge") and _CLUSTER_N.match(a)) for a in sub_args):
        found.append("cmd-no-verify")
    if sub == "config":
        found.extend(_git_config_hits(sub_args))
    if sub == "remote" and sub_args and sub_args[0] in rules.GIT_REMOTE_WRITES:
        found.append("cmd-git-config-write")
    if sub == "worktree" and sub_args and sub_args[0] in ("remove", "prune", "move", "repair"):
        found.append("cmd-git-worktree")
    found.extend(_git_main_hits(sub, sub_args))
    return found


def git_is_networked(argv):
    confs, sub, sub_args = git_parts(argv)
    if sub in ("fetch", "pull", "ls-remote", "clone", "fetch-pack", "lfs"):
        return True
    if sub == "archive" and any(a == "--remote" or a.startswith("--remote=") for a in sub_args):
        return True
    if sub == "remote" and sub_args[:1] == ["update"]:
        return True
    return sub == "submodule" and bool(sub_args[:1]) and sub_args[0] in ("update", "add", "sync")


def git_remote_ok(argv):
    """True when the remote of a networked git command is a local path or an allowlisted URL."""
    confs, sub, sub_args = git_parts(argv)
    if sub == "lfs":
        return False  # git-lfs talks to its own server (T057, R008 #9)
    if sub == "archive":  # `--remote=REPO` / `--remote REPO`: the same test as any other remote
        values = [a.split("=", 1)[1] for a in sub_args if a.startswith("--remote=")]
        values += [sub_args[i + 1] for i, a in enumerate(sub_args[:-1]) if a == "--remote"]
        return bool(values) and all(_remote_word_ok(v) for v in values)
    plain = [sub_args[i] for i in positionals(sub_args, ("--remote", "--exec", "--upload-pack"))]
    if sub in ("submodule", "remote") or not plain:
        return False
    return _remote_word_ok(plain[0])


def _remote_word_ok(remote):
    if remote.startswith(("/", "./", "../")):
        return True
    return _local_or_url(remote) and host_allowed(remote, False)


def _local_or_url(word):
    return word.startswith(("/", "./", "../")) or "://" in word or re.match(r"\A[\w-]+@[\w.-]+:", word) is not None


# -- install / env dump ----------------------------------------------------------------------
def install_hit(argv):
    name = name_of(argv[0])
    args = argv[1:]
    if re.fullmatch(r"python[0-9.]*", name) and args[:2] == ["-m", "pip"]:
        return "install" in args[2:3] + args[3:4]
    subs = rules.INSTALLERS.get(name)
    if subs is None:
        return False
    plain = [args[i] for i in positionals(args)]
    if name == "pacman":
        return any(re.fullmatch(r"-S\w*", a) for a in args)
    if name == "dpkg":
        return any(a in ("-i", "--install") for a in args)
    return bool(plain) and plain[0] in subs


def env_dump(argv):
    name = name_of(argv[0])
    args = argv[1:]
    if name == "printenv":
        return not args
    if name == "export":
        return not args or "-p" in args
    if name in ("declare", "typeset"):
        return not args or "-p" in args or (args == ["-x"])
    if name == "set":
        return not args
    if name == "compgen":
        return any(a in ("-e", "-v") for a in args)
    return False


# -- network ---------------------------------------------------------------------------------
def host_allowed(url_or_host, loopback_ok=True):
    """True if a URL (or bare host / user@host:path) names only an allowlisted destination."""
    text = url_or_host.strip()
    if "://" in text:
        parts = urlsplit(text)
        host, path = (parts.hostname or "").lower(), posixpath.normpath(parts.path or "/")
    else:
        match = _HOST_RE.match(text)
        if match is None:
            return False
        host, path = match.group("host").strip("[]").lower(), ""
    if loopback_ok and host in rules.LOOPBACK_HOSTS:
        return True
    for allowed_host, prefix in rules.ALLOWED_HOSTS:
        if host != allowed_host:
            continue
        if prefix == "":
            return True
        if path and (path.startswith(prefix) or path == prefix.rstrip("/")
                     or path.startswith(prefix.rstrip("/") + ".git")):
            return True
    return False


def network_destinations(name, args):
    """Words of a network command that name a destination."""
    value_opts = _CURL_VALUE_OPTS if name in ("curl", "wget", "aria2c") else ("-p", "-i", "-o", "-l", "-F", "-c",
                                                                           "-w", "-s", "-W", "-q", "-I")
    found = [args[i] for i in positionals(args, value_opts)]
    found.extend(args[i + 1] for i, a in enumerate(args[:-1]) if a == "--url")
    found.extend(a.split("=", 1)[1] for a in args if a.startswith("--url="))
    return [w for w in found if "://" in w or UNRESOLVED in w or (_HOST_RE.match(w) and re.search(r"[A-Za-z]", w))]


def network_hit(argv):
    name = name_of(argv[0])
    args = argv[1:]
    if name == "rsync":
        remote = [a for a in args if "://" in a or re.match(r"\A[\w-]+@[\w.-]+:", a) or re.match(r"\A[\w.-]+::", a)]
        return bool(remote) and not all(host_allowed(a, False) for a in remote)
    if name not in rules.NETWORK_COMMANDS:
        return False
    dests = network_destinations(name, args)
    loopback_ok = name not in rules.SSH_FAMILY
    return not dests or not all(host_allowed(d, loopback_ok) for d in dests)


# -- writes ----------------------------------------------------------------------------------
def write_specs(argv):
    """[(arg index in argv, op)] for the files a command writes. op: create/rewrite/edit/delete."""
    name = name_of(argv[0])
    args = argv[1:]
    pos = positionals(args, _VALUE_OPTS.get(name, ()))
    specs = []
    if name in ("rm", "rmdir", "unlink"):
        specs = [(i, "delete") for i in pos]
    elif name == "shred":
        specs = [(i, "rewrite") for i in pos]
    elif name in ("cp", "install", "ln", "mv", "rsync"):
        specs = _transfer_specs(name, args, pos)
    elif name in ("touch", "mkdir", "mkfifo"):
        specs = [(i, "create") for i in pos]
    elif name == "truncate":
        specs = [(i, "rewrite") for i in pos]
    elif name in ("chmod", "chown", "chgrp"):
        specs = [(i, "create") for i in pos[1:]]
    elif name == "tee":
        specs = [(i, "edit" if "-a" in args or "--append" in args else "rewrite") for i in pos]
    elif name in ("sed", "perl") and _in_place(args):
        has_script = any(a in ("-e", "-f", "--expression", "--file") or a.startswith("-pi") and "e" in a
                         for a in args)
        files = pos if has_script or name == "perl" else pos[1:]
        specs = [(i, "edit") for i in files]
    elif name == "dd":
        specs = [(i, "rewrite") for i, a in enumerate(args) if a.startswith("of=")]
    elif name == "git":
        specs = _git_write_specs(argv)
    elif name in ("curl", "wget"):
        specs = [(i + 1, "rewrite") for i, a in enumerate(args[:-1]) if a in ("-o", "--output", "-O", "-P")
                 and name == "wget" or a in ("-o", "--output") and name == "curl"]
    elif name == "find" and "-delete" in args:
        specs = [(i, "delete") for i in _find_roots(args)]
    return [(index + 1, op) for index, op in specs] if name != "git" else specs


_VALUE_OPTS = {"cp": ("-t", "--target-directory", "-S", "--suffix"), "mv": ("-t", "--target-directory", "-S"),
               "install": ("-t", "-m", "-o", "-g", "-S"), "ln": ("-t", "-S"), "rsync": ("-e", "--rsh"),
               "truncate": ("-s", "-r", "--size"), "tee": (), "touch": ("-d", "-t", "-r", "--date"),
               "mkdir": ("-m", "--mode"), "sed": ("-e", "-f", "--expression", "--file"),
               "perl": ("-e", "-E", "-I"), "chmod": (), "rm": (), "chown": (), "chgrp": ()}


def _in_place(args):
    return any(a == "--in-place" or a.startswith("--in-place=") or re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z.]*", a)
               for a in args)


_GREP_VALUE_OPTS = ("-A", "-B", "-C", "-m", "-g", "--glob", "-t", "--type", "--include", "--exclude", "--exclude-dir",
                    "-d", "-D", "--max-count", "-e", "--regexp", "-f", "--file", "-T", "--type-add")
_TAR_VALUE_OPTS = ("-f", "--file", "-C", "--directory", "-T", "--files-from", "-X", "--exclude-from", "--exclude", "-b",
                   "-H", "--format", "-K", "-N", "-V", "-I", "--use-compress-program")
_CP_VALUE_OPTS = ("-t", "--target-directory", "-S", "--suffix")
_RSYNC_VALUE_OPTS = ("-e", "--rsh", "--exclude", "--include", "--filter", "-f", "--files-from", "--exclude-from",
                     "--include-from", "--log-file", "--partial-dir", "--temp-dir", "-T", "--chmod", "--chown")


def recursive_roots(name, argv):
    """The argv indexes a recursive reader descends from (T052, R008 #7), [] when it defaults to the working
    directory, None when the command is not a recursive read: `grep -r/-R`, rg/ag/ack, `find`, `tar -c`,
    `cp -r/-R/-a`, rsync (sources), `du`, `ls -R`."""
    args = argv[1:]
    cluster = lambda letters: any(re.fullmatch(r"-[A-Za-z]*[%s][A-Za-z]*" % letters, a) for a in args)
    if name in ("grep", "egrep", "fgrep"):
        if not (cluster("rR") or any(a in ("--recursive", "--dereference-recursive", "--directories=recurse")
                                     for a in args) or ("-d" in args and "recurse" in args)):
            return None
        return _after_pattern(args)
    if name in ("rg", "ag", "ack"):
        return _after_pattern(args)
    if name == "find":
        return [i + 1 for i in _find_roots(args)]
    if name in ("du",) or (name == "ls" and (cluster("R") or "--recursive" in args)):
        return [i + 1 for i in positionals(args)]
    if name == "tar":
        first = args[0] if args else ""
        if not (cluster("c") or "--create" in args or (first and not first.startswith("-") and "c" in first)):
            return None
        plain = positionals(args, _TAR_VALUE_OPTS)
        if first and not first.startswith("-"):  # `tar czf out.tgz DIR`: the old-style cluster and its f value
            plain = plain[2:] if "f" in first else plain[1:]
        return [i + 1 for i in plain]
    if name == "cp" and (cluster("rRa") or any(a in ("--recursive", "--archive") for a in args)):
        plain = positionals(args, _CP_VALUE_OPTS)
        targeted = any(a in ("-t", "--target-directory") or a.startswith("--target-directory=") for a in args)
        return [i + 1 for i in (plain if targeted else plain[:-1])]
    if name == "rsync":
        return [i + 1 for i in positionals(args, _RSYNC_VALUE_OPTS)[:-1]]
    return None


def _after_pattern(args):
    plain = positionals(args, _GREP_VALUE_OPTS)
    explicit = any(a in ("-e", "--regexp", "-f", "--file") or a.startswith(("--regexp=", "--file=")) for a in args)
    return [i + 1 for i in (plain if explicit else plain[1:])]


def _find_roots(args):
    roots = []
    for i, arg in enumerate(args):
        if arg.startswith("-") or arg in ("(", "!"):
            break
        roots.append(i)
    return roots


def _transfer_specs(name, args, pos):
    target = next((i + 1 for i, a in enumerate(args[:-1]) if a in ("-t", "--target-directory")), None)
    if target is not None:
        dest = [(target, "rewrite")]
        return dest + ([(i, "delete") for i in pos] if name == "mv" else [])
    if name == "rsync":
        return [(pos[-1], "rewrite")] if len(pos) >= 2 else []
    if len(pos) < 2:
        return []
    last = [(pos[-1], "rewrite")]
    return last + ([(i, "delete") for i in pos[:-1]] if name == "mv" else [])


def _git_write_specs(argv):
    """Indexes here are into argv itself (not args)."""
    confs, sub, sub_args = git_parts(argv)
    base = len(argv) - len(sub_args)
    pos = [base + i for i in positionals(sub_args)]
    if sub == "rm":
        return [(i, "delete") for i in pos]
    if sub == "mv" and len(pos) >= 2:
        return [(i, "delete") for i in pos[:-1]] + [(pos[-1], "rewrite")]
    if sub == "clone" and len(pos) >= 2:
        return [(pos[1], "create")]
    if sub == "worktree" and sub_args[:1] == ["add"] and len(pos) >= 2:
        return [(pos[1], "create")]
    if sub == "init" and pos:
        return [(pos[0], "create")]
    return []


def decodes_input(argv):
    """True for a command that decodes or reverses its input (the front of an obfuscated pipe)."""
    name = name_of(argv[0])
    args = argv[1:]
    if name in ("base64", "basenc"):
        return any(a in ("-d", "-D", "--decode") or re.fullmatch(r"-[a-z]*d[a-z]*", a) for a in args)
    if name == "xxd":
        return any(a.startswith("-r") for a in args)
    if name == "openssl":
        return "-d" in args or "-base64" in args or "-a" in args
    return name in ("rev", "uudecode", "unhex")


# -- literal output of echo / printf (T049, R008 #3) ----------------------------------------
def _decode(text):
    from rigor_lib.trajectory_shell import DOLLAR, ansi_decode
    return ansi_decode(text).replace(DOLLAR, "$")


def echo_text(argv):
    """The text `echo ARGS` prints, or None when it is not known. Without `-e`/`-E` a backslash is read both
    ways (bash prints it, dash's echo decodes it): both texts are returned, one after the other."""
    args, newline, escapes = argv[1:], True, None
    while args and re.fullmatch(r"-[neE]+", args[0]):
        newline = newline and "n" not in args[0]
        escapes = "e" in args[0] if "e" in args[0] or "E" in args[0] else escapes
        args = args[1:]
    text = " ".join(args)
    if UNRESOLVED in text:
        return None
    end = "\n" if newline else ""
    if escapes:
        return _decode(text) + end
    if escapes is None and "\\" in text and _decode(text) != text:
        return text + "\n" + _decode(text) + end
    return text + end


def printf_text(argv):
    """The text `printf FORMAT ARGS` prints, or None when it is not known (`-v`, a directive other than %s, %b,
    %d, %i, %c and %%, an unknown piece)."""
    args = argv[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args or args[0].startswith("-") or any(UNRESOLVED in a for a in args):
        return None
    fmt, values = args[0], args[1:]
    directive = re.compile(r"%(?:%|[-+ #0]*\d*(?:\.\d+)?([sbdic]))|%")
    out, rounds = [], 0
    while True:
        pieces, pos, used = [], 0, 0
        for match in directive.finditer(fmt):
            pieces.append(_decode(fmt[pos:match.start()]))
            pos = match.end()
            if match.group(0) == "%%":
                pieces.append("%")
                continue
            kind = match.group(1)
            if kind is None:
                return None
            value = values[used] if used < len(values) else ""
            used += 1
            pieces.append(_decode(value) if kind == "b" else value[:1] if kind == "c" else value)
        pieces.append(_decode(fmt[pos:]))
        out.append("".join(pieces))
        values = values[used:]
        rounds += 1
        if not values or used == 0 or rounds > 64:
            return "".join(out) if not values or used == 0 else None
