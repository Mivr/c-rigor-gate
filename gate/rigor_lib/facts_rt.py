"""`gate//rt:require` (T128): the one gate library besides `ctest` and the third-party libraries a product may name.

`rt/require.h` defines `rigor_require(cond)`, a function whose only effect is `__builtin_trap()` when `cond` is false.
A product `c_library`, `c_binary` or `c_test` lists the label in `deps` and includes the header. What the gates do:

* `buckfiles` accepts exactly this label (any other `gate//` label is refused as before);
* `facts_third_party.split` drops its facts: gate code, nothing is checked on it, and it exports nothing;
* `symbols` does not ask for facts of it (`missing-dep-facts`) and it needs no policy entry;
* the semantic scan accepts the `__builtin_trap` the scanner finds in `rt/require.h` in a unit of a target that
  depends on the label. A `__builtin_trap` anywhere else is judged as before (`allow_builtins`).

The header is told apart by its path as the scanner reports it (`rt/require.h`, Buck's header tree without the
configuration prefix) and by the dependency: a product's own `rt/require.h` without the dependency gets no allowance.
"""

LABEL = "gate//rt:require"
HEADER = "rt/require.h"
TRAP = "__builtin_trap"
GATE_SPELLING = "//rt:require"     # how the gate prints its own target when it is the root cell


def canonical(label):
    """The `gate//` spelling of the label (`//rt:require` when the gate is the root cell)."""
    return "gate" + label if label == GATE_SPELLING else label


def is_require(label):
    return canonical(label) == LABEL


def depends(facts):
    """True when the target lists the library among its deps (deps of a library include its `exported_deps`)."""
    return any(is_require(dep) for dep in facts.deps)


def is_gate_trap(facts, name, file):
    """The identifier fact (name, file) is the trap inside the gate's header, in a target that depends on it."""
    return name == TRAP and file == HEADER and depends(facts)
