"""Add the native library to the base APK that `aapt2 link` wrote (stdlib only; runs in the `apk` action).

    apk_pack.py BASE.apk LIB OUT.apk

OUT holds the entries of BASE in their order, then `lib/arm64-v8a/<basename of LIB>`. Every entry is STORED (uncompressed:
the shared object must be mapped from the APK, and a stored manifest is valid), with the fixed time 1980-01-01 and mode 0644,
so the file is a function of its inputs. zipalign then page-aligns the object, and apksigner signs.
"""

import sys
import zipfile

ABI = "arm64-v8a"
_TIME = (1980, 1, 1, 0, 0, 0)


def _entry(name):
    info = zipfile.ZipInfo(name, _TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def pack(base, lib, out):
    with zipfile.ZipFile(base) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            if info.is_dir() or info.filename.startswith("lib/"):
                sys.exit("apk_pack: unexpected entry %r in the base APK" % info.filename)
            target.writestr(_entry(info.filename), source.read(info))
        with open(lib, "rb") as handle:
            target.writestr(_entry("lib/%s/%s" % (ABI, lib.rsplit("/", 1)[-1])), handle.read())


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    pack(argv[1], argv[2], argv[3])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
