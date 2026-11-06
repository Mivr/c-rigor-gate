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
    if sub == "push":
        found.append("cmd-git-push")
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
    if sub in ("fetch", "pull", "ls-remote", "clone"):
        return True
    if sub == "remote" and sub_args[:1] == ["update"]:
        return True
    return sub == "submodule" and bool(sub_args[:1]) and sub_args[0] in ("update", "add", "sync")


def git_remote_ok(argv):
    """True when the remote of a networked git command is a local path or an allowlisted URL."""
    confs, sub, sub_args = git_parts(argv)
    plain = [sub_args[i] for i in positionals(sub_args)]
    if sub in ("submodule", "remote") or not plain:
        return False
    remote = plain[0]
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
