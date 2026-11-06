"""Self-test only: turn a library's computed export list into a private namespace.

Reads the facts file of the server copy (`<lib>_symbols`, kind c_third_party), writes
  * a map for `llvm-objcopy --redefine-syms` (`name srv_name` for every defined symbol), and
  * a header of `#define name srv_name` lines, included first by the glue that uses the copy.
Only symbols the build computed are renamed; libc names are untouched.
"""

import json
import sys

PREFIX = "srv_"


def main(argv):
    symbols_file, map_file, header_file = argv
    with open(symbols_file, encoding="utf-8") as handle:
        document = json.load(handle)
    if document.get("kind") != "c_third_party":
        raise SystemExit("rename: not a c_third_party facts file")
    defined = sorted({s for unit in document["units"] for s in unit["defined"]})
    if not defined:
        raise SystemExit("rename: no exported symbols")
    with open(map_file, "w", encoding="ascii") as handle:
        handle.write("".join("%s %s%s\n" % (s, PREFIX, s) for s in defined))
    with open(header_file, "w", encoding="ascii") as handle:
        handle.write("/* generated: the private namespace of the self-test server library */\n"
                     "#ifndef SRV_RENAME_H\n#define SRV_RENAME_H\n")
        handle.write("".join("#define %s %s%s\n" % (s, PREFIX, s) for s in defined))
        handle.write("#endif\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
