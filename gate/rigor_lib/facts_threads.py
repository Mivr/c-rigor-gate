"""The `threads` declaration of a `c_test` against its own objects (T138), judged inside the `symbols` gate.

`symbols` is the gate that owns the symbol facts of tests today (it reads the `undefined` symbols of every unit of
every target, tests included). A `c_test(threads = True)` has a tsan results target and a test without it has none, so
the declaration decides whether a test is ever run under ThreadSanitizer:

  * `threads-undeclared`: a test whose own objects reference a thread-creation function (`THREAD_CREATE`) without
    `threads = True`: it would never run under tsan, so a race in it would pass every gate;
  * `threads-vacuous`: a `threads = True` test whose own objects reference none: the tag would only buy a tsan run of
    a single-threaded test.

"Own objects" are the units of the test target itself: a thread started by a library the test calls is not seen here.
"""

from rigor_lib.errors import InternalError
from rigor_lib.findings import finding

THREAD_CREATE = frozenset(("pthread_create", "thrd_create"))
TEST_KIND = "c_test"


def created(facts):
    """The thread-creation functions the units of `facts` reference (versions after `@` dropped), sorted."""
    names = {symbol.partition("@")[0] for unit in facts.units for symbol in unit.undefined}
    return sorted(names & THREAD_CREATE)


def findings(facts_by_label, declared):
    """`threads-undeclared` and `threads-vacuous` for every `c_test` of `facts_by_label` ({module: Facts}).

    `declared` is {module of a `c_test`: its `threads` declaration}; a test with no entry is an internal error (every
    `c_test` has a results target that carries it)."""
    found = []
    for label in sorted(facts_by_label):
        facts = facts_by_label[label]
        if facts.kind != TEST_KIND:
            continue
        if label not in declared:
            raise InternalError("no threads declaration for the test %s" % label)
        creates = created(facts)
        if creates and not declared[label]:
            found.append(finding("threads-undeclared", target=label, functions=creates))
        elif declared[label] and not creates:
            found.append(finding("threads-vacuous", target=label))
    return found
