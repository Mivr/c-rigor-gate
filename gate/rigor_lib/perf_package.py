"""The generated package `gate-perf/` (T090): one `c_perf` per perf target, with the gate-held driver sources.

Written into the grading tree after the product was copied (so `buckfiles` never sees it), next to the root `PACKAGE`
file that makes the product's targets visible to it (the same file `gate-mutants/` needs). `perf_gate` builds the
`<name>_perf` targets; `c_mutants` of a module lists them in `perf` (grade_mutants).
"""

import os
import shutil

from rigor_lib.errors import InternalError
from rigor_lib.grade_tree import write_file
from rigor_lib.perf_policy import PACKAGE


def _list(items):
    return "[%s]" % ", ".join('"%s"' % item for item in items)


def build_file_text(targets):
    calls = ['c_perf(\n    name = "%s",\n    module = "%s",\n    srcs = %s,\n    sizes = %s,\n    seed = %d,\n)\n'
             % (t.name, t.module, _list(t.srcs), "[%s]" % ", ".join(str(n) for n in t.sizes), t.seed) for t in targets]
    return 'load("@gate//rules:c.bzl", "c_perf")\n\n' + "\n".join(calls)


def write(tree, targets):
    """Write the package (BUCK and the sources). The root `PACKAGE` file is the caller's."""
    if os.path.lexists(os.path.join(tree, PACKAGE)):
        raise InternalError("%s exists in the grading tree before the gate package was written" % PACKAGE)
    write_file(tree, PACKAGE + "/BUCK", build_file_text(targets).encode("utf-8"), 0o644)
    written = {}
    for target in targets:
        for path, data in target.files:
            if path in written and written[path] != data:
                raise InternalError("perf sources: %s is two different files (target %s)" % (path, target.name))
            if path not in written:
                write_file(tree, PACKAGE + "/" + path, data, 0o644)
                written[path] = data


def remove(tree):
    shutil.rmtree(os.path.join(tree, PACKAGE), ignore_errors=True)

