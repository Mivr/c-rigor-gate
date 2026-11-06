"""Hash a fetched toolchain tree against its checked-in manifest, or generate the manifest.

    verify_tree.py gen TREE                  > MANIFEST   (prints the manifest of a real unpack)
    verify_tree.py verify TREE MANIFEST OUT              (exit 1 on any difference; OUT = marker)

Runs on an RE worker as the `verified_tree` action (toolchains/fetch.bzl); stdlib only.

A manifest line is `kind TAB x|- TAB size TAB sha256-or-target TAB path`, sorted by path bytes:
  d  directory           (`-`, 0, `-`)
  f  regular file        (executable bit, size, sha256 of the content)
  l  symlink             (`-`, 0, link target as stored)
Only the owner-execute bit is recorded: it is the one mode bit an RE input tree keeps. Any extra,
missing, retyped, resized, re-moded or altered entry is a difference; there is no tolerance.
"""

import hashlib
import os
import stat
import sys

HEADER = "# c-rigor-gate toolchain manifest v1: kind, exec, size, sha256|link target, path\n"
MAX_REPORT = 20


def entry(path, rel):
    info = os.lstat(path)
    if stat.S_ISDIR(info.st_mode):
        return ("d", "-", 0, "-", rel)
    if stat.S_ISLNK(info.st_mode):
        return ("l", "-", 0, os.readlink(path), rel)
    if not stat.S_ISREG(info.st_mode):
        return ("?", "-", 0, "special file", rel)
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1 << 20)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return ("f", "x" if info.st_mode & stat.S_IXUSR else "-", size, digest.hexdigest(), rel)


def scan(root):
    """Every entry below `root` as {path: tuple}. Symlinks are never followed."""
    found = {}
    pending = [""]
    while pending:
        rel = pending.pop()
        for name in os.listdir(os.path.join(root, rel) if rel else root):
            child = os.path.join(rel, name) if rel else name
            record = entry(os.path.join(root, child), child)
            found[child] = record
            if record[0] == "d":
                pending.append(child)
    return found


def render(found):
    lines = [HEADER]
    for path in sorted(found, key=lambda p: p.encode("utf-8", "surrogateescape")):
        kind, mode, size, value, _ = found[path]
        for text in (path, value):
            if "\t" in text or "\n" in text:
                raise SystemExit("tab or newline in %r" % text)
        lines.append("%s\t%s\t%d\t%s\t%s\n" % (kind, mode, size, value, path))
    return "".join(lines)


def parse(text):
    lines = text.split("\n")
    if not lines or lines[0] + "\n" != HEADER or lines[-1] != "":
        raise SystemExit("manifest: bad header or no final newline")
    found = {}
    for line in lines[1:-1]:
        fields = line.split("\t")
        if len(fields) != 5 or fields[0] not in ("d", "f", "l") or fields[1] not in ("x", "-"):
            raise SystemExit("manifest: bad line %r" % line)
        if not fields[2].isdigit() or fields[4] in found or fields[4] == "":
            raise SystemExit("manifest: bad or duplicate line %r" % line)
        found[fields[4]] = (fields[0], fields[1], int(fields[2]), fields[3], fields[4])
    return found


def differences(expected, actual):
    """Human-readable differences; empty when the tree is exactly the manifest."""
    out = ["missing: " + p for p in sorted(set(expected) - set(actual))]
    out += ["extra: " + p for p in sorted(set(actual) - set(expected))]
    for path in sorted(set(expected) & set(actual)):
        if expected[path] != actual[path]:
            out.append("changed: %s (manifest %s, tree %s)" % (path, expected[path][:4], actual[path][:4]))
    return out


def main(argv):
    if len(argv) == 3 and argv[1] == "gen":
        sys.stdout.write(render(scan(argv[2])))
        return 0
    if len(argv) == 5 and argv[1] == "verify":
        with open(argv[3], encoding="utf-8", errors="surrogateescape", newline="") as handle:
            text = handle.read()
        expected = parse(text)
        diff = differences(expected, scan(argv[2]))
        if diff:
            sys.stderr.write("TOOLCHAIN TREE DIFFERS FROM MANIFEST (%d differences)\n" % len(diff))
            sys.stderr.write("".join(line + "\n" for line in diff[:MAX_REPORT]))
            return 1
        with open(argv[4], "w", encoding="utf-8") as handle:
            handle.write("verified %s %d entries\n" % (hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest(), len(expected)))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
