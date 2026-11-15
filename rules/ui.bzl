"""`c_ui_probe` (U03, P004 4.2, docs/ui-model.md): the probe binary of a product's UI model.

The probe is the gate's `main` (`gate//ui/model:probe`, protocol `ui-probe/1`) linked with the product's model adapter,
a `c_library` that implements `ui/model/model.h`. The binary is a `c_binary` (the sealed C17 flags, the facts of every
mode), so it is built and graded like any product binary; there is no flag argument of any kind.

Confinement of the `uim_*` symbols is the symbols gate's, not this macro's (docs/ui-model.md, "Confinement"): the policy
denies every `uim_*` name globally and exempts the model adapter and nothing else.
"""

load("@gate//rules:c.bzl", "c_binary")

_PROBE = "gate//ui/model:probe"

def _label(macro, attr, value):
    if type(value) != "string" or ":" not in value or value.startswith("@"):
        fail("{}: `{}` must be a target label string, got {!r}".format(macro, attr, value))

def c_ui_probe(name, model):
    """A probe binary `name` from `model`, a `c_library` that implements `gate//ui/model:model` (`ui/model/model.h`).

    There is no `deps`: the adapter library carries its own dependencies, and the gates judge them as they judge any
    library. The symbols gate exempts exactly one target from the `uim_` reservation, the `model` of a `c_ui_probe`.
    Built in the release and the san mode like every `c_binary`; the grade drives the san one, the release one proves
    the interface is the same in both (docs/ui-model.md).
    """
    _label("c_ui_probe", "model", model)
    c_binary(name = name, srcs = [], deps = [model, _PROBE])
