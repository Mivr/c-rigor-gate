"""The structure limits: one table per rigor level. Gate-owned; a product never configures them.

`None` means no limit. A function body is measured from the line of `{` to the line of `}`, both included.
`statements` and `line_length` are not in the task's table: they close two ways of hiding size (a body packed
into few lines, a file packed into few long lines). `statements` equals the line limit, so formatted code never
meets it before the line limit; `line_length` is the longest physical line of a file, in bytes.
"""

from collections import namedtuple

Limits = namedtuple("Limits", "function_lines file_lines params nesting cyclomatic statements line_length")

LIMITS = {
    "L3": Limits(function_lines=50, file_lines=500, params=6, nesting=4, cyclomatic=15, statements=50,
                 line_length=160),
    "L2": Limits(function_lines=80, file_lines=800, params=8, nesting=5, cyclomatic=25, statements=80,
                 line_length=240),
    "L1": None,
}
LEVELS = ("L1", "L2", "L3")
DEFAULT_LEVEL = "L3"   # a module whose policy entry has no `level`


def strictest(levels):
    """The strictest of some levels (L3 above L2 above L1)."""
    return max(levels, key=LEVELS.index)
