"""Which modules the witness gates judge (P002, "Terms"): impl paths, test surface and the scope W.

* **impl paths**: `impl = ["core/core.c"]` per module in the gate-owned `policy.toml`; the paths an
  implementer may write and a witness replaces. An L2+ module without them is `impl-missing` (error
  at L3 and above, info at L2).
* **test surface** of module m: every product path in m's package, and in the package of every
  `c_test` that lists m directly in `deps`, that is in no module's impl paths.
* **W**: by role, over the head's layout and the changed paths `merge_base..head`:
  `implementer` - the L2+ modules whose test surface changed; `test-author` - those plus the L2+
  modules whose impl paths changed; `audit` - every L2+ module that has tests.

Packages are the directories of the targets in the layout; a path belongs to the deepest of them that
contains it. A directory with a BUCK file but no library, binary or test therefore counts toward the
enclosing package (more modules in W, never fewer). Pure functions; every malformed input is an
InternalError.
"""

from rigor_lib import contract, globs, grade_mutants, grade_policy, paths, witness_bundle
from rigor_lib.errors import InternalError
from rigor_lib.findings import SEVERITY_ERROR, SEVERITY_INFO, finding

IMPL_KEY = "impl"
JUDGED_LEVELS = ("L2", "L3", "L4", "L5")


def _check_levels(levels):
    if not isinstance(levels, dict):
        raise InternalError("levels must be a dict")
    for label, level in levels.items():
        if not isinstance(label, str) or not witness_bundle.LABEL.fullmatch(label):
            raise InternalError("bad module label in levels: %r" % (label,))
        if level not in grade_policy.LEVELS:
            raise InternalError("module %s: level must be one of %s" % (label, ", ".join(grade_policy.LEVELS)))


def _impl_globs(label, value):
    if not isinstance(value, list) or not value:
        raise InternalError("policy: module %s: impl must be a non-empty list of globs" % label)
    if not all(isinstance(item, str) for item in value):
        raise InternalError("policy: module %s: impl must hold only strings" % label)
    if len(set(value)) != len(value):
        raise InternalError("policy: module %s: duplicate impl globs" % label)
    for pattern in value:
        globs.compile_glob(pattern)  # a bad glob is an InternalError
    return list(value)


def impl_map(policy_table, levels):
    """({label: [globs]}, findings) from the parsed policy document and the module levels."""
    _check_levels(levels)
    if not isinstance(policy_table, dict):
        raise InternalError("policy must be a table")
    modules = policy_table.get("module", {})
    if not isinstance(modules, dict) or not all(isinstance(t, dict) for t in modules.values()):
        raise InternalError("policy: [module] must be a table of tables")
    mapping = {}
    for label, table in modules.items():
        if IMPL_KEY not in table:
            continue
        if not witness_bundle.LABEL.fullmatch(label):
            raise InternalError("policy: bad module label %r" % (label,))
        mapping[label] = _impl_globs(label, table[IMPL_KEY])
    found = []
    for label in sorted(levels):
        level = levels[label]
        if level in JUDGED_LEVELS and label not in mapping:
            severity = SEVERITY_INFO if level == "L2" else SEVERITY_ERROR
            found.append(finding("impl-missing", severity, module=label, level=level))
    return mapping, found


def _check_paths(items, what):
    if not isinstance(items, (list, tuple, set, frozenset)):
        raise InternalError("%s must be a list of paths" % what)
    for path in items:
        reason = paths.unsafe_path_reason(path) if isinstance(path, str) else "not a string"
        if reason is not None:
            raise InternalError("bad path in %s %r: %s" % (what, path, reason))
    return sorted(set(items))


def _check_layout(layout):
    if not isinstance(layout, grade_mutants.Layout):
        raise InternalError("layout must be a grade_mutants.Layout")
    for label in layout.libs | layout.binaries | layout.tests:
        if label not in layout.deps:
            raise InternalError("layout has no deps for %s" % label)


def package_of(label):
    """"//a/b:c" -> "a/b"; "//:c" -> "" (the root package)."""
    if not isinstance(label, str) or not witness_bundle.LABEL.fullmatch(label):
        raise InternalError("bad target label %r" % (label,))
    return label[2:label.index(":")]


def _packages(layout):
    labels = set(layout.libs | layout.binaries | layout.tests)
    for deps in layout.deps.values():
        labels.update(deps)
    return {package_of(label) for label in labels}


def _owning_package(packages, path):
    best = None
    for package in packages:
        if package == "" or path.startswith(package + "/"):
            if best is None or len(package) > len(best):
                best = package
    return best


def _modules(layout):
    return sorted(layout.libs | layout.binaries)


def _direct_tests(layout, module):
    return list(grade_mutants.direct_tests(layout, module))


def test_surface(layout, impl_map_, paths_):
    """{module: [paths of `paths_` in its test surface]} for every library and binary of the layout."""
    _check_layout(layout)
    compiled = witness_bundle.compile_impl_map(impl_map_)
    candidates = [p for p in _check_paths(paths_, "paths")
                  if not any(globs.matches(g, p) for patterns in compiled.values() for g in patterns)]
    packages = _packages(layout)
    owner = {p: _owning_package(packages, p) for p in candidates}
    surface = {}
    for module in _modules(layout):
        wanted = {package_of(module)} | {package_of(t) for t in _direct_tests(layout, module)}
        surface[module] = [p for p in candidates if owner[p] in wanted]
    return surface


def _impl_changed(compiled, module, changed):
    return any(globs.matches(g, p) for g in compiled.get(module, []) for p in changed)


def scope(role, changed_paths, layout, impl_map_, levels):
    """The sorted list W of module labels the witness gates judge."""
    if role not in contract.ROLES:
        raise InternalError("unknown role %r" % (role,))
    _check_levels(levels)
    changed = _check_paths(changed_paths, "changed paths")
    surface = test_surface(layout, impl_map_, changed)
    compiled = witness_bundle.compile_impl_map(impl_map_)
    judged = [m for m in _modules(layout) if levels.get(m) in JUDGED_LEVELS]
    if role == contract.ROLE_AUDIT:
        return [m for m in judged if _direct_tests(layout, m)]
    chosen = [m for m in judged if surface[m]]
    if role == contract.ROLE_TEST_AUTHOR:
        chosen += [m for m in judged if _impl_changed(compiled, m, changed)]
    return sorted(set(chosen))
