"""The `threads` declaration of a `c_test` against the thread creation it can reach (T138), judged inside the `symbols` gate.

`symbols` is the gate that owns the symbol facts of tests today (it reads the `undefined` symbols of every unit of
every target, tests included). A `c_test(threads = True)` has a tsan results target and a test without it has none, so
the declaration decides whether a test is ever run under ThreadSanitizer. A test is *threaded* when its own objects or
the objects of any library in its link closure (its `deps`, transitively) reference a thread-creation function
(`THREAD_CREATE`): the usual shape is a test that calls an OS-abstraction module, which calls `pthread_create`.

  * `threads-undeclared`: a threaded test without `threads = True`: it would never run under tsan, so a race in it
    would pass every gate;
  * `threads-vacuous`: a `threads = True` test that is not threaded: the tag would only buy a tsan run of
    single-threaded code.

On purpose, a test that links a threading library without ever starting a thread is threaded too: the facts say what
the closure can do, not what one run does, and declaring it costs one extra tsan run.
"""

from rigor_lib.errors import InternalError
from rigor_lib.findings import finding

THREAD_CREATE = frozenset(("pthread_create", "thrd_create"))
TEST_KIND = "c_test"


def created(facts):
    """The thread-creation functions the units of `facts` reference (versions after `@` dropped), sorted."""
    names = {symbol.partition("@")[0] for unit in facts.units for symbol in unit.undefined}
    return sorted(names & THREAD_CREATE)


def reached(facts_by_label, label):
    """(thread-creation functions referenced, sorted; the modules that reference them, sorted) over `label` and its
    link closure. Iterative; a label without facts (the sysroot libraries, gate code without facts) adds nothing."""
    functions, modules, seen, todo = set(), set(), set(), [label]
    while todo:
        current = todo.pop()
        if current in seen or current not in facts_by_label:
            continue
        seen.add(current)
        found = created(facts_by_label[current])
        if found:
            functions.update(found)
            modules.add(current)
        todo.extend(facts_by_label[current].deps)
    return sorted(functions), sorted(modules)


def findings(facts_by_label, declared):
    """`threads-undeclared` and `threads-vacuous` for every `c_test` of `facts_by_label` ({module: Facts}).

    `declared` is {module of a `c_test`: its `threads` declaration}; a test with no entry is an internal error (every
    `c_test` has a results target that carries it). `via` names the modules that reference the functions; it is
    the test itself when its own objects do."""
    found = []
    for label in sorted(facts_by_label):
        if facts_by_label[label].kind != TEST_KIND:
            continue
        if label not in declared:
            raise InternalError("no threads declaration for the test %s" % label)
        creates, via = reached(facts_by_label, label)
        if creates and not declared[label]:
            found.append(finding("threads-undeclared", target=label, functions=creates, via=via))
        elif declared[label] and not creates:
            found.append(finding("threads-vacuous", target=label))
    return found
