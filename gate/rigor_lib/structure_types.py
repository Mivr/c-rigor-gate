"""Function types for `indirect-cycle-possible` (T063): which call through a value can reach which function.

The scanner (structure_scan.py) writes canonical function types: the tokens of `RET ( P , P )` separated by single
spaces, typedefs resolved, qualifiers and parameter names dropped, integer types unified (`unsigned_long`) and
`enum X` as the token `enum`. C11 6.5.2.2p9 makes a call through a pointer of a type that is not compatible with
the function's type undefined, so a call site of type T can only reach a function of a type compatible with T,
unless the program converts a function pointer between types. Those conversions are facts too (casts, unions,
memcpy, va_arg); a type involved in one loses the benefit and is treated as "may call anything" (fail closed).

What this module decides is only the C compatibility of two canonical types. Unknown (None) matches everything.
"""

INTEGERS = frozenset(("char", "signed_char", "unsigned_char", "short", "unsigned_short", "int", "unsigned_int",
                      "long", "unsigned_long", "long_long", "unsigned_long_long", "_Bool", "enum"))


def parameters(canonical):
    """The canonical type's parameters at its own level: a list of token lists, [] for `(void)`, None if the type
    is unprototyped (`()`)."""
    toks = canonical.split()
    at = toks.index("(")
    body = toks[at + 1:-1]
    if not body:
        return None
    found, depth, current = [], 0, []
    for tok in body:
        if depth == 0 and tok == ",":
            found.append(current)
            current = []
            continue
        depth += (tok == "(") - (tok == ")")
        current.append(tok)
    found.append(current)
    return [] if found == [["void"]] else found


def unprototyped(canonical):
    return parameters(canonical) is None


def variadic(canonical):
    found = parameters(canonical)
    return bool(found) and found[-1] == ["..."]


def wild(canonical):
    """A function of such a type may be called through a pointer of nearly any type: `int f()` (C11 6.7.6.3p15
    gives it compatibility with any prototype whose parameters need no promotion) and a variadic function."""
    return unprototyped(canonical) or variadic(canonical)


def same_token(a, b):
    return a == b or (a == "enum" and b in INTEGERS) or (b == "enum" and a in INTEGERS)


def compatible(a, b):
    """May a function of canonical type `a` be called through a pointer of canonical type `b` (either may be
    None = unknown, which matches)? Looser than C where unsure, never stricter."""
    if a is None or b is None:
        return True
    if wild(a) or wild(b):
        return True
    ta, tb = a.split(), b.split()
    return len(ta) == len(tb) and all(same_token(x, y) for x, y in zip(ta, tb))
