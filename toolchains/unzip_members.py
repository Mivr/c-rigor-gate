"""Unpack only the matching members of a zip archive (stdlib only; runs on an RE worker).

    unzip_members.py list ARCHIVE OUT                 (writes "L|F size name" for every member)
    unzip_members.py extract ARCHIVE OUT MEMBERS      (MEMBERS: one pattern per line, at least one)

A pattern names a file or a directory (and everything below it), written from the archive root. `*`, `?` and `[...]`
match inside ONE path component and never across a `/`, so `a/include/*.h` selects the headers of that directory only.
Symlinks and the owner-execute bit are restored from the zip's Unix attributes. The archive is not trusted: an absolute
or `..` member name, a repeated name, a symlink to an absolute or escaping target, or a path that runs through a symlink
of the archive is refused, files are created with O_EXCL | O_NOFOLLOW, and a pattern that matches nothing fails, like
`tar --wildcards` in `fetched_tree`.
"""

import os
import posixpath
import re
import stat
import sys
import zipfile


def _regex(pattern):
    """The regular expression of one pattern: `*` and `?` stay inside a path component, `[...]` is a class."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and pattern.find("]", i + 2) > 0:
            j = pattern.index("]", i + 2)
            body = pattern[i + 1:j]
            out.append("[" + ("^" if body.startswith("!") else "") + re.escape(body.lstrip("!")).replace("\\-", "-") + "]")
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out))


def matches(name, regex):
    """Does `name` (no trailing slash) equal the pattern, or lie below a directory that does?"""
    parts = name.split("/")
    return any(regex.fullmatch("/".join(parts[:n])) for n in range(1, len(parts) + 1))


def check_name(name):
    """The normalised member name; exits on an absolute, escaping, empty-component or NUL-carrying one."""
    bare = name[:-1] if name.endswith("/") else name
    parts = bare.split("/")
    if bare == "" or name.startswith("/") or "\0" in name or "\\" in name or any(p in ("", ".", "..") for p in parts):
        sys.exit("unzip_members: refusing member name %r" % name)
    return bare


def check_link(name, target):
    """Refuse a symlink target that is absolute or leaves the archive root."""
    if target == "" or target.startswith("/") or "\0" in target:
        sys.exit("unzip_members: refusing symlink %r -> %r (absolute or empty target)" % (name, target))
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
    if resolved == ".." or resolved.startswith("../") or resolved == ".":
        sys.exit("unzip_members: refusing symlink %r -> %r (escapes the tree)" % (name, target))


def _make_dirs(out, rel):
    """Create the directories of `rel` below `out`, refusing to pass through a symlink."""
    here = out
    for part in rel.split("/"):
        here = os.path.join(here, part)
        if os.path.islink(here):
            sys.exit("unzip_members: %r runs through a symlink" % rel)
        os.makedirs(here, exist_ok=True)


def extract(archive, out, patterns):
    if not patterns:
        sys.exit("unzip_members: no member patterns given")
    regexes = {p: _regex(p.rstrip("/")) for p in patterns}
    hit = {p: False for p in patterns}
    seen = set()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = check_name(info.filename)
            if name in seen:
                sys.exit("unzip_members: member %r appears twice" % name)
            seen.add(name)
            matched = False
            for p, regex in regexes.items():
                if matches(name, regex):
                    hit[p] = True
                    matched = True
            if not matched:
                continue
            mode = info.external_attr >> 16
            if info.filename.endswith("/"):
                _make_dirs(out, name)
                continue
            if "/" in name:
                _make_dirs(out, posixpath.dirname(name))
            dest = os.path.join(out, name)
            if stat.S_ISLNK(mode):
                target = zf.read(info).decode()
                check_link(name, target)
                os.symlink(target, dest)
                continue
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with zf.open(info) as src, os.fdopen(fd, "wb") as dst:
                while True:
                    block = src.read(1 << 20)
                    if not block:
                        break
                    dst.write(block)
                os.fchmod(dst.fileno(), 0o755 if mode & stat.S_IXUSR else 0o644)
    missing = [p for p, ok in hit.items() if not ok]
    if missing:
        sys.exit("unzip_members: no member matches: " + ", ".join(missing))


def main(argv):
    if len(argv) == 4 and argv[1] == "list":
        with zipfile.ZipFile(argv[2]) as zf, open(argv[3], "w", encoding="utf-8") as out:
            for info in zf.infolist():
                mode = info.external_attr >> 16
                out.write("{} {} {}\n".format("L" if stat.S_ISLNK(mode) else "F", info.file_size, info.filename))
        return 0
    if len(argv) == 5 and argv[1] == "extract":
        with open(argv[4], encoding="utf-8") as handle:
            patterns = [line.rstrip("\n") for line in handle if line.strip()]
        extract(argv[2], argv[3], patterns)
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
