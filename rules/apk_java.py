"""javac, then d8: the Java sources of a `c_apk` become its classes.dex (stdlib only; runs in the `apk` action on RE).

    apk_java.py --javac CMD --d8 CMD --android-jar JAR --min-api N [--package P]... --out classes.dex SRC.java...

javac is the pinned JDK's, run as `java -m jdk.compiler/com.sun.tools.javac.Main` (toolchains//:javac). The sources are
compiled against the platform android.jar as the boot class path, as Java 8 source and class files (the language level of minSdk
28; `--release 8` would need the JDK's `ct.sym`, which the pinned tree does not hold, docs/toolchain.md), with `-Werror` and every
lint category (except `options`, which only reports that the pinned `-source 8` is obsolete in JDK 21) and without annotation
processors: `-proc:none`, and `-implicit:none` plus an empty source path so that only the named files are compiled. d8 then
dexes the class files with `--min-api N` into exactly one classes.dex (a second one is an error). The file names are plain, sorted,
and nothing is read from the environment.
"""

import os
import re
import shlex
import subprocess
import sys
import tempfile

KEYS = ("javac", "d8", "android-jar", "min-api", "out")


def run(command, *args):
    done = subprocess.run(shlex.split(command) + [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, check=False)
    text = done.stdout.decode("utf-8", "replace")
    if done.returncode != 0:
        sys.exit("apk_java: %s failed (exit %d):\n%s" % (command.split()[-1], done.returncode, text[-3000:]))
    return text


_PACKAGE_LINE = re.compile(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", re.M)


def package_problems(sources, packages):
    """Every source must have a `package` line naming one of the listed `--package`s (no default package, no unlisted one)."""
    found = []
    for path in sources:
        with open(path, encoding="utf-8") as handle:
            match = _PACKAGE_LINE.search(handle.read())
        if not match:
            found.append("%s has no package line" % path)
        elif match.group(1) not in packages:
            found.append("%s is in the package %s, which is not in java_packages (%s)" % (path, match.group(1), ", ".join(packages)))
    return found


def compile_sources(javac, android_jar, sources, classes):
    run(javac, "-source", "8", "-target", "8", "-bootclasspath", android_jar, "-Xlint:all,-options", "-Werror", "-proc:none",
        "-implicit:none", "-sourcepath", classes, "-encoding", "UTF-8", "-d", classes, *sorted(sources))


def class_files(directory):
    found = []
    for base, _, names in os.walk(directory):
        found += [os.path.join(base, n) for n in names if n.endswith(".class")]
    return sorted(found)


def dex(d8, android_jar, min_api, files, out_dir):
    if not files:
        sys.exit("apk_java: there is no class file to dex")
    run(d8, "--min-api", min_api, "--lib", android_jar, "--output", out_dir, *files)
    written = sorted(os.listdir(out_dir))
    if written != ["classes.dex"]:
        sys.exit("apk_java: d8 must write exactly classes.dex, it wrote %s" % written)
    return os.path.join(out_dir, "classes.dex")


def build(javac, d8, android_jar, min_api, sources, scratch, skip=()):
    """The path of the classes.dex of `sources`, built under `scratch`; `skip` names class files (relative, `org/x/A$B.class`)
    left out of the dex (the selftest builds a dex that lacks a declared class this way)."""
    classes, out_dir = os.path.join(scratch, "classes"), os.path.join(scratch, "dex")
    os.mkdir(classes)
    os.mkdir(out_dir)
    compile_sources(javac, android_jar, sources, classes)
    files = [f for f in class_files(classes) if os.path.relpath(f, classes) not in skip]
    return dex(d8, android_jar, min_api, files, out_dir)


def main(argv):
    opts, sources, packages, args = {}, [], [], list(argv[1:])
    while args:
        arg = args.pop(0)
        if arg == "--package" and args:
            packages.append(args.pop(0))
        elif arg.startswith("--") and arg[2:] in KEYS and args:
            opts[arg[2:]] = args.pop(0)
        elif not arg.startswith("-") and arg.endswith(".java"):
            sources.append(arg)
        else:
            sys.exit(__doc__)
    if sorted(opts) != sorted(KEYS) or not sources or not packages:
        sys.exit(__doc__)
    problems = package_problems(sources, packages)
    if problems:
        sys.exit("apk_java: " + "; ".join(problems))
    with tempfile.TemporaryDirectory() as scratch:
        produced = build(opts["javac"], opts["d8"], opts["android-jar"], opts["min-api"], sources, scratch)
        with open(produced, "rb") as handle, open(opts["out"], "wb") as target:
            target.write(handle.read())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
