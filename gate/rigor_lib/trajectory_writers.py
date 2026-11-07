"""Writers beyond a plain target argument (T061, R008 #16): pure argv parsing, no state.

* a generic `-o`/`--output[=]` of a compiler (cc, gcc, clang, ld, rustc, `go build`) or of `sort`;
* `gawk -i inplace` (the files it rewrites);
* commands that write files the audit cannot name, below a known directory: `tar -x` (`-C DIR`), `unzip` (`-d DIR`);
* the options of `patch`, `git apply`, `git clean` and `xargs` that decide what they write;
* the files a unified or git diff touches (`patch`, `git apply` of a patch whose text the audit knows).
"""

import posixpath
import re

from rigor_lib import trajectory_cmds as cmds
from rigor_lib import trajectory_shell as shell
from rigor_lib.trajectory_shell import UNRESOLVED

_COMPILER_RE = re.compile(r"\A(?:[\w.+]+-)*(?:cc|c\+\+|gcc|g\+\+|clang|clang\+\+|tcc|cpp|ld|ld\.lld|ld\.gold|lld|as|"
                          r"rustc)(?:-[0-9][0-9.]*)?\Z")


# File-name endings of patch leftovers (T077, B26): a glob that ends in one of these literal suffixes names only such
# leftovers. The test-file rule knows names like `test_*`, `*_test.*` and `*_tests.*` and the directories `tests/` and
# `test/`; a name ending in `.orig` or `.rej` is a leftover of `patch`, never a test or a fixture.
PATCH_LEFTOVER_SUFFIXES = (".orig", ".rej")  # only for a delete that cannot remove a directory: `recursive_delete`
_GLOB_CHARS = "*?["


def patch_leftover_glob(path):
    """True when the last component of `path` is a glob whose literal tail (after its last glob character) is a patch
    leftover suffix, and no earlier component is a glob: `dir/*.orig`, `dir/x*.rej`. Not `*`, `*.or*`, `*.c`,
    `test_*`, `d*/x.orig` or a plain `x.orig`."""
    head, _, last = path.rpartition("/")
    if any(ch in head for ch in _GLOB_CHARS) or not any(ch in last for ch in _GLOB_CHARS):
        return False
    tail = last[max(last.rfind(ch) for ch in _GLOB_CHARS) + 1:]
    return tail.endswith(PATCH_LEFTOVER_SUFFIXES)


def recursive_delete(argv):
    """True unless the command is one that cannot remove a directory tree (T077): `rm` and `git rm` without a
    recursive flag (`-r`, `-R`, any cluster holding one, `--recursive` or a prefix of it), `rmdir` and `unlink`.
    Everything else that deletes (`find -delete`, `mv` of a directory, `git clean`) counts as recursive."""
    name = cmds.name_of(argv[0])
    args = argv[1:]
    if name in ("rmdir", "unlink"):
        return False
    if name == "git":
        _, sub, args = cmds.git_parts(argv)
        if sub != "rm":
            return True
    elif name != "rm":
        return True
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("--"):
            if len(arg) >= 5 and "--recursive".startswith(arg.split("=", 1)[0]):
                return True
        elif arg.startswith("-") and set(arg[1:]) & {"r", "R"}:
            return True
    return False


def is_compiler(name):
    return _COMPILER_RE.match(name) is not None


def compiler_outputs(args):
    """[(index in args, text)] of `-o FILE`, `-oFILE`, `--output FILE`, `--output=FILE`."""
    found, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg in ("-o", "--output") and i + 1 < len(args):
            found.append((i + 1, args[i + 1]))
            i += 2
            continue
        if arg.startswith("--output="):
            found.append((i, arg[len("--output="):]))
        elif arg.startswith("-o") and len(arg) > 2:
            found.append((i, arg[2:]))
        i += 1
    return found


_SORT_VALUED = "ktSTo"  # short options of sort that take a value (the rest of the cluster, else the next word)
_SORT_LONG_VALUED = ("--key", "--field-separator", "--buffer-size", "--temporary-directory", "--parallel",
                     "--files0-from", "--batch-size", "--compress-program", "--random-source", "--sort")


def sort_outputs(args):
    """[(index in args, text)] of sort's output file: `-o FILE`, `-oFILE`, a cluster ending in o (`-uo FILE`),
    `--output FILE`, `--output=FILE`."""
    found, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            break
        if arg.startswith("--output="):
            found.append((i, arg[len("--output="):]))
        elif arg == "--output" and i + 1 < len(args):
            found.append((i + 1, args[i + 1]))
            i += 1
        elif arg in _SORT_LONG_VALUED:
            i += 1
        elif arg.startswith("-") and not arg.startswith("--") and arg != "-":
            for at, letter in enumerate(arg[1:], start=1):
                if letter in _SORT_VALUED:
                    rest = arg[at + 1:]
                    if letter == "o" and rest:
                        found.append((i, rest))
                    elif letter == "o" and i + 1 < len(args):
                        found.append((i + 1, args[i + 1]))
                    if not rest:
                        i += 1
                    break
        i += 1
    return found


_AWK_VALUED = ("-f", "-v", "-F", "-i", "-l", "-e", "-E", "-W", "--file", "--assign", "--field-separator",
               "--include", "--load", "--source", "--exec")
_AWK_PROGRAM_OPTS = ("-f", "--file", "-e", "--source", "-E", "--exec")


def awk_inplace_files(args):
    """Indexes (in args) of the files `gawk -i inplace` rewrites; [] without the inplace extension."""
    inplace = any(a in ("-iinplace", "-iinplace.awk", "--include=inplace", "--include=inplace.awk") or (
        a in ("-i", "--include") and args[k + 1:k + 2] in (["inplace"], ["inplace.awk"])) for k, a in enumerate(args))
    if not inplace:
        return []
    pos = cmds.positionals(args, _AWK_VALUED)
    program_given = any(a in _AWK_PROGRAM_OPTS or a.startswith(("--file=", "--source=", "--exec=")) for a in args)
    files = pos if program_given else pos[1:]
    return [i for i in files if not re.match(r"[A-Za-z_]\w*=", args[i])]  # `var=value` is an assignment


def _cluster(args, letters, first_plain=False):
    pattern = re.compile(r"-[A-Za-z]*[%s][A-Za-z]*" % letters)
    if any(pattern.fullmatch(a) for a in args):
        return True
    return first_plain and bool(args) and not args[0].startswith("-") and any(c in args[0] for c in letters)


def tar_extract_dir(args):
    """(index in args or None, directory text) that `tar -x` extracts below; None when tar does not extract to
    disk (no `-x`/`--extract`/`--get`, or `-O`/`--to-stdout`/`--to-command`). The last `-C DIR` wins."""
    if not (_cluster(args, "x", first_plain=True) or "--extract" in args or "--get" in args):
        return None
    if _cluster(args, "O", first_plain=True) or "--to-stdout" in args or any(
            a.startswith("--to-command") for a in args):
        return None
    found = (None, ".")
    for i, arg in enumerate(args):
        if arg in ("-C", "--directory") and i + 1 < len(args):
            found = (i + 1, args[i + 1])
        elif arg.startswith("--directory="):
            found = (i, arg[len("--directory="):])
        elif arg.startswith("-C") and len(arg) > 2:
            found = (i, arg[2:])
    return found


def unzip_dir(args):
    """(index in args or None, directory text) unzip extracts below; None for a listing, test or pipe run."""
    if _cluster(args, "ltpzZv"):
        return None
    found = (None, ".")
    for i, arg in enumerate(args):
        if arg == "-d" and i + 1 < len(args):
            found = (i + 1, args[i + 1])
        elif arg.startswith("-d") and len(arg) > 2:
            found = (i, arg[2:])
    return found


def _long_or_short(args, i, short, long):
    """(value, index of the value word, words used) of `-X V`, `-XV`, `--long V`, `--long=V` at args[i], or None."""
    arg = args[i]
    if arg in (short, long) and i + 1 < len(args):
        return args[i + 1], i + 1, 2
    if long and arg.startswith(long + "="):
        return arg[len(long) + 1:], i, 1
    if short and arg.startswith(short) and len(arg) > len(short) and not arg.startswith("--"):
        return arg[len(short):], i, 1
    return None


_PATCH_VALUED = (("-p", "--strip"), ("-d", "--directory"), ("-i", "--input"), ("-o", "--output"),
                 ("-r", "--reject-file"), ("-B", "--prefix"), ("-Y", "--basename-prefix"), ("-z", "--suffix"),
                 ("-V", "--version-control"), ("-D", "--ifdef"), ("-F", "--fuzz"), ("-g", "--get"))


def patch_options(args):
    """{strip, directory, input, output, original, patchfile, dry} of a `patch` command (texts; None when absent)."""
    opts = {"strip": None, "directory": None, "input": None, "output": None, "original": None, "patchfile": None,
            "dry": False, "indexes": set()}
    plain, i, keys = [], 0, {"-p": "strip", "-d": "directory", "-i": "input", "-o": "output"}
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run" or arg == "-C" or arg == "--check":
            opts["dry"] = True
        if arg.startswith("-") and arg != "-":
            for short, long in _PATCH_VALUED:
                got = _long_or_short(args, i, short, long)
                if got is not None:
                    value, at, used = got
                    if short in keys:
                        opts[keys[short]] = value
                        opts["indexes"].add(at)
                    i += used
                    break
            else:
                i += 1
            continue
        plain.append(i)
        i += 1
    if plain:
        opts["original"] = plain[0]
    if len(plain) > 1:
        opts["patchfile"] = plain[1]
    return opts


def git_apply_options(sub_args):
    """{strip, directory, files, writes} of `git apply` (files: indexes of the patch files in sub_args)."""
    opts = {"strip": 1, "directory": None, "files": [], "writes": True}
    report_only = any(a in ("--check", "--stat", "--numstat", "--summary") for a in sub_args)
    if report_only and "--apply" not in sub_args:
        opts["writes"] = False
    i = 0
    while i < len(sub_args):
        arg = sub_args[i]
        if re.fullmatch(r"-p[0-9]+", arg):
            opts["strip"] = int(arg[2:])
        elif arg == "-p" and i + 1 < len(sub_args) and sub_args[i + 1].isdigit():
            opts["strip"] = int(sub_args[i + 1])
            i += 1
        elif arg.startswith("--directory="):
            opts["directory"] = arg[len("--directory="):]
        elif arg in ("--directory", "--exclude", "--include", "-C", "--whitespace", "--build-fake-ancestor") and \
                i + 1 < len(sub_args):
            if arg == "--directory":
                opts["directory"] = sub_args[i + 1]
            i += 1
        elif not arg.startswith("-") or arg == "-":
            opts["files"].append(i)
        i += 1
    return opts


def git_clean_paths(sub_args):
    """(writes, [indexes of pathspecs]) of `git clean`: no writes for a dry run (`-n`, `--dry-run`)."""
    if any(a == "--dry-run" or re.fullmatch(r"-[A-Za-z]*n[A-Za-z]*", a) for a in sub_args):
        return False, []
    return True, cmds.positionals(sub_args, ("-e", "--exclude"))


def xargs_replace(prefix):
    """The replacement string of the `xargs` among the wrapper words in front of a command (`-I R`, `-iR`, `-i`,
    `--replace[=R]`), "" when xargs appends its input, None when there is no xargs."""
    found = None
    for k, word in enumerate(prefix):
        if cmds.name_of(word) != "xargs":
            continue
        found = ""
        for j in range(k + 1, len(prefix)):
            arg = prefix[j]
            if arg == "-I" and j + 1 < len(prefix):
                found = prefix[j + 1]
            elif arg.startswith("-I") and len(arg) > 2:
                found = arg[2:]
            elif arg in ("-i", "--replace"):
                found = "{}"
            elif arg.startswith("-i") and len(arg) > 2:
                found = arg[2:]
            elif arg.startswith("--replace="):
                found = arg[len("--replace="):]
    return found


def write_targets(argv):
    """[(argv index, op, path text)] of every file a command writes by name: the targets of
    `trajectory_cmds.write_specs`, plus a compiler's or sort's `-o`/`--output` (op `build` for a compiler: a
    program, not a text the audit should know), the files `gawk -i inplace` rewrites and the value of
    `--target-directory=DIR`."""
    name = cmds.name_of(argv[0])
    args = argv[1:]
    found = [(i, op, argv[i]) for i, op in cmds.write_specs(argv)]
    if is_compiler(name) or (name == "go" and args[:1] == ["build"]):
        skip = 1 if name == "go" else 0
        found += [(i + 1 + skip, "build", text) for i, text in compiler_outputs(args[skip:])]
    elif name == "sort":
        found += [(i + 1, "rewrite", text) for i, text in sort_outputs(args)]
    elif name in ("awk", "gawk"):
        found += [(i + 1, "edit", args[i]) for i in awk_inplace_files(args)]
    elif name in ("cp", "mv", "install", "ln"):
        found += [(i + 1, "rewrite", a[len("--target-directory="):]) for i, a in enumerate(args)
                  if a.startswith("--target-directory=")]
    return found


_TRANSFER_VALUED = {"cp": ("-S", "--suffix"), "mv": ("-S", "--suffix"), "install": ("-m", "-o", "-g", "-S", "--mode",
                                                                               "--owner", "--group", "--suffix"),
                    "ln": ("-S", "--suffix")}


def transfer(argv):
    """The layout of `cp`/`mv`/`install`/`ln` (T061, R008 #17): {sources: [argv indexes], target: argv index of the
    target word or None, text: the target text, dir: True when the target must be a directory (`-t DIR`,
    `--target-directory=DIR`, more than one source)}; None for another command, `install -d`, or `-T`
    (`--no-target-directory`: the target is the file itself)."""
    name = cmds.name_of(argv[0])
    if name not in _TRANSFER_VALUED:
        return None
    args = argv[1:]
    if any(a in ("-T", "--no-target-directory") for a in args) or (name == "install" and any(
            a in ("-d", "--directory") for a in args)):
        return None
    valued = _TRANSFER_VALUED[name] + ("-t", "--target-directory")
    pos = [i + 1 for i in cmds.positionals(args, valued)]
    for i, arg in enumerate(args):
        if arg in ("-t", "--target-directory") and i + 1 < len(args):
            return {"sources": pos, "target": i + 2, "text": args[i + 1], "dir": True}
        if arg.startswith("--target-directory="):
            return {"sources": pos, "target": i + 1, "text": arg[len("--target-directory="):], "dir": True}
    if len(pos) < 2 and not (name == "ln" and len(pos) == 1):
        return None
    if len(pos) == 1:  # `ln -s TARGET`: the link is made in the working directory
        return {"sources": pos, "target": None, "text": ".", "dir": True}
    # `ln -n`: a target that is a link to a directory is replaced, not entered
    follow = not (name == "ln" and ("--no-dereference" in args or any(
        re.fullmatch(r"-[A-Za-z]*n[A-Za-z]*", a) for a in args)))
    return {"sources": pos[:-1], "target": pos[-1], "text": argv[pos[-1]], "dir": len(pos) > 2, "follow": follow}


def into_dir(directory, source):
    """The path a copy of `source` gets inside `directory` (`cp a/b.c dir/` writes dir/b.c)."""
    base = source.rstrip("/").rsplit("/", 1)[-1] or source
    return directory.rstrip("/") + "/" + base if directory.rstrip("/") else "/" + base


def tree_targets(argv):
    """[(argv index or None, directory text)] below which a command writes files it does not name: `tar -x`
    (`-C DIR`, else the working directory) and `unzip` (`-d DIR`, else the working directory)."""
    name = cmds.name_of(argv[0])
    found = tar_extract_dir(argv[1:]) if name in ("tar", "bsdtar", "gtar") else (
        unzip_dir(argv[1:]) if name == "unzip" else None)
    if found is None:
        return []
    index, text = found
    return [(None if index is None else index + 1, text)]


# -- the files a diff touches ----------------------------------------------------------------
_HUNK_RE = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_GIT_HEADER_RE = re.compile(r"diff --git (\S+) (\S+)\Z")


def _strip(name, level):
    if name == "/dev/null":
        return None
    name = name.split("\t", 1)[0].strip()
    if level is None:
        return name
    parts = [p for p in name.split("/") if p]
    return "/".join(parts[level:]) if len(parts) > level else None


def diff_targets(text, level):
    """[(path, op)] a unified or git diff writes (op: create, edit, delete), paths with `level` leading
    components stripped (None: as written); None when the text holds no file header (nothing the audit can name).
    Hunk bodies are skipped by their line counts, so a removed line that looks like `--- x` is not a header."""
    lines = text.split("\n")
    found, i, old = [], 0, None
    while i < len(lines):
        line = lines[i]
        hunk = _HUNK_RE.match(line)
        if hunk is not None:
            left = int(hunk.group(1) if hunk.group(1) is not None else 1)
            right = int(hunk.group(2) if hunk.group(2) is not None else 1)
            i += 1
            while i < len(lines) and (left > 0 or right > 0):
                body = lines[i]
                if body.startswith("-"):
                    left -= 1
                elif body.startswith("+"):
                    right -= 1
                elif not body.startswith("\\"):
                    left, right = left - 1, right - 1
                i += 1
            continue
        if line.startswith("--- "):
            old = line[4:]
        elif line.startswith("+++ ") and old is not None:
            new = line[4:]
            before, after = _strip(old, level), _strip(new, level)
            if after is None and before is not None:
                found.append((before, "delete"))
            elif after is not None:
                found.append((after, "create" if old.split("\t", 1)[0].strip() == "/dev/null" else "edit"))
                if before is not None and before != after:
                    found.append((before, "edit"))
            old = None
        elif line.startswith(("rename from ", "rename to ", "copy to ")):  # git names these without a/ and b/
            found.append((line.split(" ", 2)[2].strip(), "delete" if line.startswith("rename from") else "create"))
        i += 1
    return found or None


_STDIN_ARG = "\x00stdin"  # where xargs puts the words it reads (never a path: normalize refuses NUL)


class WritersMixin:
    """Methods of the Analyzer for the writers above (T061, R008 #16)."""

    def modelled_writes(self, item, argv, name, raw, flags):
        """Audit the writes of `tar -x`, `unzip`, `patch`, `git apply`, `git clean` and `xargs <writer>`; return the
        argv indexes that are write targets (not reads)."""
        skip = set()
        for index, text in tree_targets(argv):
            if index is not None:
                skip.add(index)
            self.write_tree(text, raw)
        skip |= self.note_links(argv, name, raw)
        self.move_clones(argv, name)
        if name == "patch":
            skip |= self._patch(item, argv, raw)
        elif name == "git":
            self._git_tree_writes(item, argv, raw)
        self._xargs_writes(item, argv, raw, flags)
        return skip

    def write_tree(self, text, raw):
        """Files written below the directory `text` whose names the audit cannot know (an extracted archive, a patch
        of unknown text, `git clean`, `xargs rm`). Outside the worktree and the scratch dirs that is `write-outside`;
        in a scratch dir nothing there is protected; in the worktree a protected directory is `tamper-protected`, any
        other is `write-unresolved` (review: a protected or test file could be among them)."""
        if UNRESOLVED in text:
            self._unresolved_write(text.rstrip("/") + "/" + UNRESOLVED, raw)
            return
        normal = self.policy.normalize(text, self.cwd)
        if normal is None:
            self.add("write-unresolved", raw, text)
            return
        self.dirs.add(normal)
        for known in [f for f in self.files if self.policy.is_inside(normal, f)]:
            self._content_changed(known, "rewrite")  # whatever was known of the files below is gone
        normal = self.policy.through_links(normal)
        if normal is None:
            self.add("write-unresolved", raw, text)
            return
        if not self.policy.write_ok(normal):
            self.add("write-outside", raw, text)
            return
        rel = self.policy.relative_to_worktree(normal)
        if rel is None:
            return
        probes = [rel, rel + "/x"] if rel != "." else [rel]
        if any(self.task.is_protected(p) for p in probes):
            self.add("tamper-protected", raw, text)
        else:
            self.add("write-unresolved", raw, text)

    def note_links(self, argv, name, raw):
        """`ln [-s] SOURCE... DEST` and `cp -s/-l`: record each link in the policy's virtual table (T061, R008 #18), so
        later paths through it resolve to its target whatever the disk holds. A relative symbolic source is relative
        to the link's own directory (`ln -s ../policy src/p` points at <worktree>/policy), unless `-r`/`--relative`
        (then the working directory). The source is read-checked as resolved; returns its argv indexes."""
        args = argv[1:]
        flags = [a for a in args if a.startswith("-") and not a.startswith("--")]
        if name == "ln":
            symbolic = "--symbolic" in args or any("s" in a[1:] for a in flags)
        elif name == "cp" and ("--symbolic-link" in args or "--link" in args or any(
                ("s" in a[1:] or "l" in a[1:]) and not a.startswith("-S") for a in flags)):
            symbolic = "--symbolic-link" in args or any("s" in a[1:] for a in flags)
        else:
            return set()
        layout = transfer(argv)
        if layout is None:
            return set()
        relative = "--relative" in args or any("r" in a[1:] for a in flags) and name == "ln"
        into = layout["dir"] or self.is_dir(layout["text"], layout.get("follow", True))
        for index in layout["sources"]:
            source = argv[index]
            dest = into_dir(layout["text"], source) if into else layout["text"]
            link = self.policy.normalize(dest, self.cwd)
            if link is None:
                continue
            key = self.policy.add_link(link, None)
            base = posixpath.dirname(key) if symbolic and not relative else self.cwd
            target = self.policy.normalize(source, base)
            self.policy.links[key] = target
            if target is not None:
                saved = set(self.read_set)
                self.read_word(target, raw, "")  # the target as the link sees it, not as the cwd would
                self.read_set = saved
            elif UNRESOLVED in source:
                self.add("path-unresolved", raw, source.replace(UNRESOLVED, "$("))
        return set(layout["sources"])

    def move_clones(self, argv, name):
        """`mv` and `cp -r` of a proven local clone (or a directory holding one) from one declared scratch directory to
        another (T072, B23): the proof moves with `mv` and is copied by `cp -r`, with its taint. A move or copy out of
        the scratch directories ends the proof of what moved; a destination that replaces a clone ends its proof."""
        flags = [a for a in argv[1:] if a.startswith("-") and not a.startswith("--")]
        args = argv[1:]
        if name == "mv":
            copy = False
        elif name == "cp" and ("--recursive" in args or any(set(a[1:]) & set("rRa") for a in flags)) and not (
                "--symbolic-link" in args or "--link" in args or any(set(a[1:]) & set("sl") for a in flags)):
            copy = True
        else:
            return
        layout = transfer(argv)
        if layout is None or not self.clones:
            return
        into = layout["dir"] or self.is_dir(layout["text"], layout.get("follow", True))
        scratch = self.policy.own[1:]
        for index in layout["sources"]:
            source = self.policy.normalize(argv[index], self.cwd)
            dest = self.policy.normalize(into_dir(layout["text"], argv[index]) if into else layout["text"], self.cwd)
            if source is None or dest is None:
                continue
            moved = {c: t for c, t in self.clones.items() if self.policy.is_inside(source, c)}
            for old in [c for c in self.clones if self.policy.is_inside(dest, c)]:
                self.clones.pop(old)  # replaced by what lands there
            for old, tainted in moved.items():
                new = dest + old[len(source):]
                if not copy:
                    self.clones.pop(old, None)
                if any(self.policy.is_inside(b, source) for b in scratch) and any(
                        self.policy.is_inside(b, new) for b in scratch):
                    self.clones[new] = tainted

    def known_text(self, path_text):
        """The text of a file as this transcript wrote it, or None when the audit does not know it."""
        normal = self.policy.normalize(path_text, self.cwd)
        if normal is None or normal in self.unknown or normal in self.dirty:
            return None
        return self.files.get(normal)

    def _stdin_text(self, item):
        """The text on a command's stdin when the audit knows it: a quoted (or literal) here-document, or `< f` of a
        file whose text the transcript wrote. "" when stdin is not redirected, None when its text is unknown."""
        command = item.cmd
        if command.heredocs:
            doc = command.heredocs[0]
            return doc.body if doc.quoted or shell.body_is_literal(doc.body) else None
        for redirect in command.redirects:
            if redirect.op == "<" and redirect.fd in (None, "0"):
                return self.known_text(self.expand(redirect.target, self.env_now))
        return ""

    def _apply_diff(self, text, level, directory, raw, basenames=False):
        """Audit the files a diff of known text writes, below `directory`; a diff with no file header the audit can
        read writes files it cannot name (write_tree)."""
        targets = diff_targets(text, level) if text else None
        if targets is None:
            self.write_tree(directory, raw)
            return
        for path, op in targets:
            names = {path, path.rsplit("/", 1)[-1]} if basenames else {path}
            for name in sorted(names):
                full = name if name.startswith("/") else directory.rstrip("/") + "/" + name
                self.write(full, op, raw)

    def _patch(self, item, argv, raw):
        """`patch`: `-o FILE` is the only file written; an explicit original file is edited; otherwise the files
        named by the diff (known text: `< f`, `-i f`, the patch file argument, a here-document), else unknown files
        below `-d DIR` or the working directory."""
        args = argv[1:]
        opts = patch_options(args)
        skip = {i + 1 for i in opts["indexes"]}
        if opts["dry"]:
            return skip
        if opts["output"] is not None:
            self.write(opts["output"], "rewrite", raw)
            return skip
        directory = opts["directory"] or "."
        if opts["original"] is not None:
            skip.add(opts["original"] + 1)
            self.write(args[opts["original"]], "edit", raw)
            return skip
        source = opts["input"] or (args[opts["patchfile"]] if opts["patchfile"] is not None else None)
        text = self.known_text(source) if source is not None else self._stdin_text(item)
        level = int(opts["strip"]) if opts["strip"] and opts["strip"].isdigit() else None
        self._apply_diff(text, level, directory, raw, basenames=level is None)
        return skip

    def _git_tree_writes(self, item, argv, raw):
        """`git apply` (the files its diff names, else unknown files in the repository) and `git clean` (its
        pathspecs, else unknown files below the directory). Outside the agent's dirs a writing git command is
        already `write-outside` (T057), except `git apply`, judged here."""
        _, sub, sub_args = cmds.git_parts(argv)
        if sub not in ("apply", "clean"):
            return
        base = self.git_write_dir(argv)
        if base is None:
            self.add("write-unresolved", raw, "git " + sub)
            return
        if sub == "clean":
            writes, paths = git_clean_paths(sub_args)
            if not writes or not self.policy.write_ok(base):
                return  # a dry run; or outside the agent's dirs, which git_shared_store reports
            for index in paths:
                self.write(self.policy.normalize(sub_args[index], base) or UNRESOLVED, "delete", raw)
            if not paths:
                self.write_tree(base, raw)
            return
        opts = git_apply_options(sub_args)
        if not opts["writes"]:
            return
        top = self.policy.worktree if self.policy.relative_to_worktree(base) is not None else base
        if opts["directory"]:
            top = top.rstrip("/") + "/" + opts["directory"]
        files = [sub_args[i] for i in opts["files"]]
        texts = [self.known_text(f) if f != "-" else self._stdin_text(item) for f in files] or [self._stdin_text(item)]
        for text in texts:
            self._apply_diff(text, opts["strip"], top, raw)

    def _xargs_writes(self, item, argv, raw, flags):
        """`... | xargs <writer>`: the writer's targets come from stdin. When the stage before is `find ROOTS`, they
        are below those roots (audited like `find -exec`); otherwise unknown: `write-outside` when the working directory
        is outside the agent's dirs, else `write-unresolved` (review; orchestrator ruling 4)."""
        prefix = item.words[:len(item.words) - len(argv)]
        replace = xargs_replace(prefix)
        if replace is None:
            return
        probe = list(argv) if replace else list(argv) + [_STDIN_ARG]
        mark = replace or _STDIN_ARG
        fed = [(op, text) for _, op, text in write_targets(probe) if mark in text]
        if not fed:
            return
        feeder = flags["feeder"].get(id(item))
        roots = None
        if feeder is not None and feeder.argv and cmds.name_of(feeder.argv[0]) == "find":
            fargs = feeder.argv[1:]
            roots = [fargs[i] for i in cmds.find_roots(fargs)] or ["."]
        if roots:
            for root in roots:
                for op, text in fed:
                    self.write(text.replace(mark, root), op, raw)
            return
        word = "xargs " + cmds.name_of(argv[0])
        if UNRESOLVED in self.cwd:
            self.add("write-unresolved", raw, word)
        elif not self.policy.write_ok(self.cwd):
            self.add("write-outside", raw, word)
        else:
            self.add("write-unresolved", raw, word)
