#!/usr/bin/env -S python3 -I
"""Make, hash and check witness bundles (docs/witness.md). Not wired into `rigor grade` yet.

    gate/tools/witness.py from-commit --repo R --commit C --module LABEL --paths GLOB... [--module ...]
                                      --product NAME --out DIR
    gate/tools/witness.py digest DIR
    gate/tools/witness.py check DIR --product NAME --impl LABEL=GLOB...

`from-commit` copies the files of commit C that match each module's globs into a new bundle at DIR
(which must not exist), reading git blobs as the grading tree does, never a working directory. Symlinks,
gitlinks and a path claimed by two modules are refused. The bundle is loaded and checked before it is
moved into place, and its digest is printed. `digest` prints `witness_sha256`. `check` validates a bundle
against a product name and impl globs. Exit 0 = done, 2 = any defect (nothing is ever a pass by default).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

from rigor_lib import gitrun, globs, grade_tree, paths, witness_bundle, witness_scope  # noqa: E402
from rigor_lib.errors import InternalError  # noqa: E402

ORIGIN_FROM_COMMIT = "from-commit"
_FILE_MODES = ("100644", "100755")


class _ModuleAction(argparse.Action):
    """`--module L` opens a group; the `--paths` that follow belong to it."""

    def __call__(self, parser, namespace, values, option_string=None):
        groups = getattr(namespace, "groups", None) or []
        if option_string == "--module":
            if groups and groups[-1][1] is None:
                parser.error("--module %s has no --paths" % groups[-1][0])
            groups.append([values, None])
        else:
            if not groups or groups[-1][1] is not None:
                parser.error("--paths must follow its own --module")
            groups[-1][1] = list(values)
        namespace.groups = groups


def impl_from_pairs(pairs):
    """{label: [globs]} through the same validation as the policy's `impl` keys."""
    tables = {}
    for label, patterns in pairs:
        if not witness_bundle.LABEL.fullmatch(label):
            raise InternalError("bad module label %r" % label)
        tables.setdefault(label, {"impl": []})["impl"].extend(patterns)
    mapping, _ = witness_scope.impl_map({"module": tables}, {})
    return mapping


def _owner(compiled, text):
    owners = [label for label, patterns in compiled.items() if any(globs.matches(g, text) for g in patterns)]
    if len(owners) > 1:
        raise InternalError("%s matches the globs of %s" % (text, ", ".join(sorted(owners))))
    return owners[0] if owners else None


def collect(repo, commit, impl):
    """[(product path, bytes)] of commit's files that match the impl globs, sorted."""
    compiled = {label: [globs.compile_glob(p) for p in patterns] for label, patterns in impl.items()}
    files = []
    for entry in grade_tree.list_tree(repo, commit):
        text = paths.match_text(entry.path)
        reason = paths.unsafe_path_reason(text)
        if reason is not None:
            raise InternalError("commit holds a bad path %r: %s" % (paths.display_path(entry.path), reason))
        if _owner(compiled, text) is None:
            continue
        if entry.mode not in _FILE_MODES or entry.kind != "blob":
            raise InternalError("%s is not a plain file (mode %s)" % (paths.display_path(entry.path), entry.mode))
        files.append((text, grade_tree.read_blob(repo, entry)))
    return sorted(files)


def manifest_text(product, labels, commit):
    lines = ["product = %s" % json.dumps(product)]
    for label in sorted(labels):
        lines += ["", "[module.%s]" % json.dumps(label), "origin = %s" % json.dumps(ORIGIN_FROM_COMMIT),
                  "written_against = %s" % json.dumps(commit)]
    return "\n".join(lines) + "\n"


def _write_bundle(root, product, impl, commit, files):
    with open(os.path.join(root, witness_bundle.MANIFEST), "x", encoding="utf-8") as handle:
        handle.write(manifest_text(product, impl, commit))
    os.mkdir(os.path.join(root, witness_bundle.FILES_DIR))
    for text, data in files:
        grade_tree.write_file(os.path.join(root, witness_bundle.FILES_DIR), text, data, 0o644)


def from_commit(repo, commit_rev, groups, product, out):
    if os.path.lexists(out):
        raise InternalError("output exists: %s" % out)
    impl = impl_from_pairs(groups)
    commit = gitrun.resolve_commit(repo, commit_rev)
    files = collect(repo, commit, impl)
    parent = os.path.dirname(os.path.abspath(out))
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".witness-", dir=parent)
    try:
        _write_bundle(staging, product, impl, commit, files)
        bundle = witness_bundle.load(staging)
        witness_bundle.check(bundle, product, impl)
        os.rename(staging, out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return bundle


def _split_impl(item):
    label, separator, pattern = item.partition("=")
    if separator == "" or label == "" or pattern == "":
        raise InternalError("--impl wants LABEL=GLOB, got %r" % item)
    return label, [pattern]


def build_parser():
    parser = argparse.ArgumentParser(prog="witness.py", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("from-commit", allow_abbrev=False)
    make.add_argument("--repo", required=True)
    make.add_argument("--commit", required=True)
    make.add_argument("--module", action=_ModuleAction, required=True)
    make.add_argument("--paths", action=_ModuleAction, nargs="+", required=True)
    make.add_argument("--product", required=True)
    make.add_argument("--out", required=True)
    digest = sub.add_parser("digest", allow_abbrev=False)
    digest.add_argument("dir")
    check = sub.add_parser("check", allow_abbrev=False)
    check.add_argument("dir")
    check.add_argument("--product", required=True)
    check.add_argument("--impl", required=True, nargs="+")
    return parser


def run(args):
    if args.command == "from-commit":
        if args.groups[-1][1] is None:
            raise InternalError("--module %s has no --paths" % args.groups[-1][0])
        bundle = from_commit(args.repo, args.commit, args.groups, args.product, args.out)
        return "%s %s (%d files)" % (witness_bundle.digest(bundle), args.out, len(bundle.files))
    bundle = witness_bundle.load(args.dir)
    if args.command == "check":
        impl = impl_from_pairs([_split_impl(item) for item in args.impl])
        witness_bundle.check(bundle, args.product, impl)
        return "ok %s" % witness_bundle.digest(bundle)
    return witness_bundle.digest(bundle)


def main(argv):
    args = build_parser().parse_args(argv)
    try:
        print(run(args))
    except Exception as exc:  # any failure is exit 2, never a pass
        print("witness.py: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
