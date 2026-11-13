"""Unpack only the matching members of a zip archive (stdlib only; runs on an RE worker).

    unzip_members.py list ARCHIVE OUT                 (writes "L|F size name" for every member)
    unzip_members.py extract ARCHIVE OUT MEMBERS      (MEMBERS: one fnmatch pattern per line)

Symlinks and the owner-execute bit are restored from the zip's Unix attributes. A pattern that
matches nothing fails, like `tar --wildcards` in `fetched_tree`.
"""

import fnmatch
import os
import stat
import sys
import zipfile


def extract(archive, out, patterns):
    hit = {p: False for p in patterns}
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            matched = False
            for p in patterns:
                # A pattern names a file, or a directory (trailing component) and everything below it.
                if fnmatch.fnmatchcase(name.rstrip("/"), p) or name.startswith(p.rstrip("/") + "/"):
                    hit[p] = True
                    matched = True
            if not matched:
                continue
            dest = os.path.join(out, name)
            if name.endswith("/"):
                os.makedirs(dest, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                os.symlink(zf.read(info).decode(), dest)
                continue
            with zf.open(info) as src, open(dest, "wb") as dst:
                while True:
                    block = src.read(1 << 20)
                    if not block:
                        break
                    dst.write(block)
            os.chmod(dest, 0o755 if mode & stat.S_IXUSR else 0o644)
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
