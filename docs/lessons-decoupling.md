# Lessons from decoupling a C codebase, and the rules they became

For maintainers of other projects graded by this gate. This is what went wrong in one real C monorepo built by
coding agents, how it was measured, which gate rule each lesson became, and how to adopt the rules in a codebase that
already has the problem without stopping work. The rules are generic; everything product-specific is a few lines in
the product's own files ([decoupling.md](decoupling.md) has the formats and a minimal example).

The codebase: about 180 libraries and 740 test targets, every one small, statically allocated, layered by an
architecture contract, with mutation testing on almost every module. Each module passed every check on the day it
landed. The problems below are properties of the whole, and no per-module check saw them grow.

## 1. What went wrong, and how it was measured

**Most declared dependencies were not used.** Agents copy the dependency list of the neighbouring target: it always
builds. Measured over every build file: of about 9,800 product dependencies declared by test targets, about 7,900
(four in five) were used by nothing in the test, and of about 1,100 declared by libraries, about 660. A dependency
counted as used when the target's own files include one of its headers or its objects reference one of its symbols.
An unused dependency is not harmless: it is linked, it is an input of every action of the target, and it makes the
declared graph useless as a description of the real one, so every tool that reads the graph (layering, fan-out,
"what do I rebuild") reads fiction.

**Public headers included what the library did not export.** About 410 times a public header included another
module's header while the module was a private dependency. The build then only works if every dependent lists that
module too, although it never uses it. This is where a large share of the unused dependencies came from, and why
they could not simply be deleted: the export has to be fixed first.

**Unit tests linked the application.** A "unit test" of one component built its inputs by running the real
neighbouring components. 107 of the 743 tests linked more than ten application modules, and 128 linked at least one
component that was not the one under test. Such a test is slow to link, breaks when a neighbour changes, and does
not say which module is wrong when it fails.

**Mutation cost multiplied by every dependent test.** A module's mutants were run against every test that listed the
module. With the lists above, that is most tests of the tree for a low-level module: each mutant is linked into, and
run by, test binaries that were never written to check that module, and each of those runs is keyed on everything the
test links.

**A small change invalidated most of the tree.** The base library was linked by 645 of the 743 tests, and a plain
value-types module by 358. With cached builds the cost of a change is the set of actions whose inputs changed; with
honest dependency lists that set is the real dependents, with copied lists it is nearly everything.

**Hidden references go stale when two chains of work change one module.** A dependency that is declared but not
used, a type reached through somebody else's header, a test that only compiles because a third module happens to
export something: none of these is visible at the place where the module is edited. Two independent lines of work
that both change a shared module can each be green alone and still break targets neither of them touched.

**Interfaces were edited in place.** When a shared header changes, every consumer has to be adapted in the same
change. Such a change is a change to everything at once: it cannot be reviewed, cached or rolled back by parts, and
parallel work on two consumers conflicts by construction.

## 2. The rule each lesson became
All are findings of gate `decoupling`; exact definitions and fields are in [decoupling.md](decoupling.md).

| Lesson | Finding | What it checks | What it cannot see |
|---|---|---|---|
| declared but unused | `unused-dep` | every declared product dependency is used: an own file includes one of its headers, or an object references one of its symbols | an include under `#if 0` counts; an include spelled through a macro does not; a header reached only through another header is, on purpose, not a use |
| headers that leak | `missing-export`, `needless-export` | `exported_deps` is exactly what the public headers include | private headers by convention live under `src/`; a public header outside that convention is treated as public |
| unit tests linking the app | `unit-test-links-component` | a unit test links no component or composition module of another package; fakes, contracts and plain libraries are free | whether the test calls what it links (that is `unused-dep`); whether a fake is faithful |
| test levels | `unleveled-test`, `library-in-test-package` | integration and simulation tests live in declared packages without a module; those tests are never a module's own tests, so they never feed a mutant run | whether an integration test is a good one |
| mutation cost | (selection rule of `mutants`, not a finding) | a module's mutants run against the tests of its own package only; without one it is `module-without-tests` | a mutant only a foreign test would have killed now survives: the module's own tests have to be complete |
| contracts that grow behaviour | `contract-has-behaviour` | an interface module depends only on contracts and declared base modules, calls nothing outside them but the allowed `mem*` functions, holds no writable data | a pure helper that is too clever; behaviour hidden in a macro |
| interfaces edited in place | `interface-changed` | once another package depends on a contract, the declarations of its headers at the base of a change are all still there, unchanged and in order, at the head; additions are allowed and reported | a meaning that changes without the text changing; text that changes without the meaning changing is refused (reformat in a new version) |
| the cost of one edit | `metadata.fan_out` (a report) | per library: how many targets and how many tests link it | what a test actually exercises |

## 3. Adopting the rules without stopping work: the baseline ratchet
A codebase with thousands of existing violations cannot turn these rules on as errors, and a rule that only reports
is ignored. The ratchet does both jobs:

1. Write `products/<p>/decoupling.toml`: which modules are contracts, components, the composition layer, fakes, and
   which packages hold integration and simulation tests. Start with what exists; a kind with no module yet may be an
   empty list.
2. Grade the main branch once with that file and no baseline. The grade fails, listing every violation, and keeps
   its facts in `<work>/facts`.
3. Generate the list of tolerated violations and commit it next to the declarations:
   ```sh
   gate/tools/decoupling.py baseline --product-repo R --commit <main> --product <p> --facts <work>/facts \
       > products/<p>/decoupling-baseline.toml
   ```
4. Pin the gate. From this moment a change that **adds** a violation fails with the rule's name, and ordinary work
   is otherwise untouched.
5. Every change that **removes** violations lands together with the gate commit that drops those entries (the same
   tool on the change's head; `--check` verifies a file). Until it does, the grade fails with `stale-baseline` and
   names the entries. This is the part that makes the list shrink: an entry that outlived its violation would be a
   licence to bring the violation back.
6. When a rule's list is empty, delete its key. The rule is then a plain error.

Frozen interfaces have no baseline. They start empty (nothing is a contract until you declare one) and are enforced
from the first contract on.

## 4. The order that worked
1. **Declared equals used, exports first.** Fix `missing-export` before `unused-dep`: once a library exports what its
   public header includes, its dependents can drop the dependencies they only carried for that header. This step is
   mechanical, changes no behaviour, and makes every later measurement true.
2. **Test-side fakes.** Give each interface one generic fake (it records calls and returns scripted results, and has
   tests of its own) next to the interface, and move unit tests onto it. Tests that really need several real
   components are integration tests: move them to a module-less package and declare it.
3. **Contracts.** Move the shared types, constants and function-pointer tables out of the components into interface
   modules that hold no behaviour. Components then depend on contracts, never on each other; only the composition
   layer names concrete implementations.
4. **Versioning.** Only now freeze: a contract that others use changes by a new module next to it; consumers move one
   change at a time; the old one is deleted when its last user is gone.

The order matters. Freezing first would freeze the mess; fakes before honest dependency lists cannot be measured;
contracts before fakes leave every test linking the implementations anyway.

## 5. What the owner decided along the way, and why
* **A module's mutants run against its own package's tests only.** A module must be proven by its own tests. Tests of
  other packages that happen to reach it are not evidence about it, and counting them multiplied the mutation cost by
  the number of dependents while hiding modules that had no real tests of their own.
* **Pure domain leaves are used directly, not mocked.** A pure function over values (a parser, a validator, a table
  of rules) is checked by its own tests, and its consumers call the real one, exactly as they call a string library.
  Mocking it would test the mock. Only things with state, time, I/O or a choice of implementation sit behind an
  interface. In the gate's terms: such modules are in none of the declared kinds and are free to link.
* **A safety-critical family may stay one cohesive subsystem with direct calls.** Where a safety argument has to hold
  against the real code (the real encoder, the real timing arithmetic), a fake between the members of that family
  would make the tests prove nothing that matters. The family keeps direct calls inside, is small and changes
  rarely, and meets the rest of the application through one interface. In the gate's terms: its members are not
  declared components.
* **Interfaces are frozen once shared and change only by a new version.** "Extend or version, never edit" costs a
  second module now and then; it buys changes that can be made, reviewed, cached and reverted one consumer at a time.

## 6. What we would tell another project
* Measure the declared graph against the used graph before believing any number derived from it.
* Make the default path the cheap one: if copying a neighbour's dependency list always passes, it will be copied.
* A rule introduced as a report is not a rule. Introduce it as an error over a baseline that can only shrink.
* Put the test level in the layout (where the test lives), not in a naming convention or a comment.
* The checks are text and symbol comparisons that take seconds and need no new build. None of this needed a new
  analysis tool, only the decision to fail the build.
