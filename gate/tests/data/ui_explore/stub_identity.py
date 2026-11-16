"""The scene identity of the explorer's stub probe (U24; split out of stub_probe.py, at its 500-line limit). The modes
are frame-facts modes that also announce `identity`; every other mode replies `err identity unsupported`:

    ident        `state main`, the title (element title, msgid toy.title, one argument) and the button (a msgid)
    identbad     the title's line has no identity (a grammar violation: a protocol error)
    identkey     a node line whose key no semantic node has (the model's breach: kind contract)
    identdup     the title's key twice (the model's breach: kind contract)
    identmut     a correct reply, but the call changes the model: the notice's label (identity is read-only)
"""

MODES = ("ident", "identbad", "identkey", "identdup", "identmut")
TITLE = "node\ttitle\ttitle\ttoy.title\t1\t=Toy"
BUTTON = "node\tbutton\t-\ttoy.press\t0"


def reply(mode, model):
    """The reply lines of `identity` in `mode`; `model` is the stub's Model (identmut changes it)."""
    if mode not in MODES:
        return ["err identity unsupported"]
    nodes = {"identbad": ["node\ttitle\t-\t-\t0", BUTTON], "identkey": ["node\tghost\tt\t-\t0", BUTTON],
             "identdup": [TITLE, BUTTON, "node\ttitle\tother\t-\t0"]}.get(mode, [TITLE, BUTTON])
    if mode == "identmut":
        model.notice = model.notice + "!"
    return ["ok identity lines %d" % (len(nodes) + 1), "state\tmain"] + nodes
