"""Unpack the pinned release tarball of a vendored library, exactly.

Runs as a build action on RE (Python 3 stdlib only; the worker has no bzip2 binary, `tarfile` does it).
The archive is already checked against its sha256 by Buck2 (`download_file`). On top of that:

* only regular files and directories exist inside the selected directories (a link, a device or an
  absolute or `..` member name is an error);
* the set of `*.c` / `*.h` files below the selected directories must equal the committed manifest
  exactly (an extra or a missing file is an error), so nothing can ride along unseen.

Usage: extract.py --archive A --top DIR --dirs d1,d2 --manifest FILE --out OUT [--list]
`--list` prints the manifest of the archive instead of extracting (used to regenerate files.bzl).
"""

import argparse
import os
import sys
import tarfile

SOURCE_SUFFIXES = (".c", ".h")


def fail(message):
    sys.stderr.write("extract: %s\n" % message)
    raise SystemExit(1)


def wanted(rel, dirs):
    return any(rel == d or rel.startswith(d + "/") for d in dirs)


def selected(archive, top, dirs):
    """(relative path, TarInfo) of every file or directory below the selected directories."""
    found = []
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            name = member.name
            if name.startswith("/") or ".." in name.split("/"):
                fail("unsafe member name %r" % name)
            if not name.startswith(top + "/"):
                continue
            rel = name[len(top) + 1:]
            if not wanted(rel, dirs):
                continue
            if member.isdir():
                continue
            if not member.isreg():
                fail("%s is not a regular file" % name)
            found.append((rel, member))
    return found


def manifest_of(found):
    return sorted(rel for rel, _ in found if rel.endswith(SOURCE_SUFFIXES))


def main(argv):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--dirs", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--out")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    dirs = args.dirs.split(",")
    found = selected(args.archive, args.top, dirs)
    actual = manifest_of(found)
    if args.list:
        sys.stdout.write("".join(rel + "\n" for rel in actual))
        return 0
    with open(args.manifest, encoding="utf-8") as handle:
        expected = sorted(handle.read().split())
    if actual != expected:
        extra, missing = sorted(set(actual) - set(expected)), sorted(set(expected) - set(actual))
        fail("archive and manifest differ: extra %s, missing %s" % (extra[:10], missing[:10]))
    with tarfile.open(args.archive, "r:*") as tar:
        for rel, member in found:
            if not rel.endswith(SOURCE_SUFFIXES):
                continue
            target = os.path.join(args.out, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            source = tar.extractfile(member)
            with open(target, "wb") as handle:
                handle.write(source.read())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
