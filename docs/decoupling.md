# Gate `decoupling`: declared equals used, tests at their level, frozen interfaces

A product whose modules meet only over small, stable interfaces compiles little, relinks little and mutates cheaply.
This gate holds the rules that keep it so, and a ratchet that lets a codebase that is not there yet adopt them without
stopping: every existing violation is listed once, nothing new may be added, and the list can only shrink.
Why these rules exist, and the order that worked for adopting them: [lessons-decoupling.md](lessons-decoupling.md).

The gate sits after `layering` in `gate/order.txt`. It reads the assembled tree (the `BUCK` files and the `#include`
lines), the facts `symbols` and `layering` already built (no build of its own), and two gate-owned files next to
`product.toml`: `decoupling.toml` (what the product's modules are) and `decoupling-baseline.toml` (what is still
tolerated). Both are snapshotted with the other product files; the info finding `decoupling-inputs` carries their
sha256, so the verdict commits to them.

## Not adopted: PASS with info `not-applicable`
A product without `decoupling.toml` has not adopted the rules: the gate is PASS with the one info finding
`not-applicable`, before anything is read (the baseline file is not even opened). With the file, the gate needs the
facts, so it is NOT_RUN unless `toolchain`, `assemble` and `buckfiles` passed and the facts built.

## What the product declares
```toml
# products/<product>/decoupling.toml: every key is optional
[modules]
contract    = ["//apps/shop/contracts/**"]    # interface modules: types, constants, function-pointer tables
component   = ["//apps/shop/parts/**"]        # implementations; they meet only through contracts
composition = ["//apps/shop/main:*"]          # the modules that bind implementations to interfaces
fake        = ["//apps/shop/contracts/clock:fake"]   # test-only libraries: fakes and test kits
frozen      = []                              # besides the contracts: modules whose public headers are frozen
[contract]
may_use = ["//lib/base/**"]                   # what a contract may depend on besides other contracts
allow   = ["memcpy", "memset", "memcmp"]      # the only outside symbols a contract's objects may reference (default)
[tests]
integration = ["//apps/shop/itest/**"]        # packages without a module; their tests are integration tests
simulation  = ["//apps/shop/sim/**"]          # the same, counted apart
```
An entry is a module pattern as in [layering.md](layering.md) (`//pkg:name`, `//pkg:*`, `//pkg/**`) or the name of a
layer of the product's `architecture.toml`, which stands for that layer's patterns. The `[testkit]` modules of the
architecture are fakes too. A module in none of the lists (a generic library, a pure domain module) is not restricted
by the kind rules: it is used directly, like any library. Unknown keys, wrong types, an entry that is neither a
pattern nor a layer: exit 2.

Words used below. A *module* is a `c_library` (or a `c_catalog`, `c_embed`) that is not a fake, or a `c_binary`. A
target's *own files* are its `srcs` and `headers`. A *public header* is a `headers` entry outside the package's `src/`
directory. A target *links* everything it reaches through `deps` and `exported_deps`.

## The rules
Every finding is an error and carries `rule`, `severity`, `target`, the rule's own fields and `entry`, the key the
baseline lists.

| Rule | Entry | What it means |
|---|---|---|
| `unused-dep` | `<target> -> <dep>` | A `c_library`, `c_binary`, `c_test` or `c_fuzz` declares the product target `dep` (field `list`: `deps` or `exported_deps`) and does not use it. *Used* means: an own file of the target has an `#include` that names a header of the dep, **or** an object of the target has an undefined symbol the dep defines. |
| `missing-export` | `<library> -> <dep>` | A public header of the library includes a header of `dep`, and `dep` is not in its `exported_deps`. Every dependent then has to list `dep` itself, without using it. |
| `needless-export` | `<library> -> <dep>` | `dep` is used and in `exported_deps`, and no public header includes it: it belongs in `deps`. |
| `unit-test-links-component` | `<test> -> <module>` | A unit test (a `c_test` in a package that holds a module) links a `component` or `composition` module of another package. Fakes, contracts and every undeclared module are free. For the tests of a composition module, what that module itself links is free too (binding is its job). |
| `unleveled-test` | `<test>` | A `c_test` in a package without a module that neither `[tests]` list names: it is no module's unit test and not a declared integration or simulation test. |
| `library-in-test-package` | `<library>` | A module in a declared integration or simulation package. Those packages hold tests (and fakes) only. |
| `contract-has-behaviour` | `<module> -> <dep>`, `<module> : <symbol>`, `<module> : static-data` | A `contract` module depends on something that is neither a contract nor in `may_use` (`reason` `dep`), its objects reference a symbol that none of its deps defines and `allow` does not list (`symbol`), or it defines writable static data (`static-data`). |
| `stale-baseline` | the stale entry (field `list`: its rule) | The baseline lists a violation the tree no longer has (below). |
| `interface-changed` | none: never baselined | A frozen header lost or changed a declaration (below). |

Test levels follow from the layout: a `c_test` of a declared `simulation` or `integration` package has that level,
any other test in a package with a module is a *unit* test, the rest are unleveled. The metadata counts the tests
per level (`tests`). Tests of the declared packages are never a module's own tests: `mutants` and the witness scope
leave them out even if a library sits in such a package (`grade_mutants.own_tests`), so they are never an input of a
mutant run.

`metadata.fan_out` is a report, never a finding: per library, how many non-test targets and how many tests link it
(`per_module`), with the largest and the summed number of tests. It is what one edit of that library relinks.

### Frozen interfaces: `interface-changed`
A module is *frozen* when it is a `contract` or listed under `[modules] frozen`, is not a fake, and, **at the merge
base of the change**, a target of another package depends on it. Its frozen headers are its public headers and the
headers of the same module they include. For each, the top-level declarations at the base (a preprocessor line; any
other text up to a `;` outside braces and parentheses, or to the closing brace of a function body; comments removed,
blank runs folded) must all be present at the head, unchanged and in the same order.

| Finding | When |
|---|---|
| `interface-changed`, `reason` `declaration`, `file`, `line` (in the base file) | a base declaration is gone or different: a struct that gained a member, an enumerator added or renumbered, a macro value, a prototype |
| `interface-changed`, `reason` `header-removed` | the header is gone while the module stays |
| `interface-changed`, `reason` `macro-shadows`, `name` | a new `#define` or `#undef` of a name the base declarations use |
| `interface-changed`, `reason` `pragma` | a new `#pragma` |
| `interface-extended` (info), `declarations` | new declarations were added and nothing above applies |

There is no baseline and no approval: the way to change a frozen interface is a new module next to it
(`contracts/clock_v2` beside `contracts/clock`), which is not frozen until something outside its package depends on
it at a base. Consumers move one change at a time, and the old module is deleted when nothing depends on it (a
module that is gone at the head is not judged; a dependent that was left behind no longer builds). An interface that
nothing outside its package uses yet may still be edited.

## The baseline ratchet
```toml
# products/<product>/decoupling-baseline.toml: one sorted list per rule, absent = empty
unused-dep = [
    "//apps/shop/parts/cart:cart -> //lib/base/text:text",
]
unit-test-links-component = []
```
* A violation of the tree that its rule's list does not name is an **error named after the rule**. This holds from
  the first grade: nothing new gets in.
* An entry that is not a violation of the graded head is the error **`stale-baseline`**, always. The change that
  removes a violation therefore lands together with a gate whose list no longer has the entry: the list shrinks with
  every fix, and a fixed problem cannot come back unnoticed. `metadata.rules` gives, per rule, `violations`, `new` and
  `stale`, and the findings name every entry, so the new file is mechanical (the tool below).
* A file with an unknown rule, an entry that is not a key, or a list that is not sorted and duplicate-free is exit 2.
  Without the file nothing is tolerated.

Why stale entries are errors and not notes: a note is never acted on, and an entry that outlives its violation is a
licence to reintroduce it. The cost is one more gate pin for a change that fixes a violation. In practice only the
change that edits the target can fix an `unused-dep` or an export (they depend on the target's own files and build
file), so an unrelated change rarely meets it; `unit-test-links-component` can be fixed from a distance (a module
far below the test drops an edge), and then the finding lists exactly which entries to drop.

### The tool
```sh
gate/tools/decoupling.py baseline --product-repo R --commit C --product NAME --facts WORK/facts > products/NAME/decoupling-baseline.toml
gate/tools/decoupling.py baseline --product-repo R --commit C --product NAME --facts WORK/facts --check
```
It prints the file for the tree of commit `C`: every violation, sorted, the same bytes on every run; `--check`
compares with the committed file instead (exit 1 and `+`/`-` lines on stderr). `--facts` is the facts directory of a
grade of that commit (`<work>/facts`, kept after every grade), and with it the output is exactly what the gate
computes. Without `--facts` nothing needs to be built, and the answer is an approximation for a first look: a target
"references a symbol" of a dep when its own files name a symbol of the dep's policy `exports`, and the parts of
`contract-has-behaviour` that need objects see nothing. Pin only a file made with `--facts`.

## Adopting the rules in a product: a minimal example
An imaginary product: two components (`cart`, `pay`), one contract (`clock`) with its fake, a composition module, a
unit test per component and one integration test.
```
apps/shop/contracts/clock/   clock.h (clock_ops_t), fake.h + fake.c   BUCK: c_library clock, c_library fake
apps/shop/parts/cart/        cart.h, src/cart.c, tests/cart_test.c    BUCK: c_library cart, c_test cart_test
apps/shop/parts/pay/         pay.h, pay.c, pay_test.c                 BUCK: c_library pay,  c_test pay_test
apps/shop/main/              main.h, main.c                           BUCK: c_library main (deps: cart, pay)
apps/shop/itest/flow/        flow_test.c                              BUCK: c_test flow_test (deps: cart, pay)
```
```python
# apps/shop/parts/cart/BUCK
c_library(name = "cart", srcs = glob(["src/*.c"]), headers = ["cart.h"],
          exported_deps = ["//apps/shop/contracts/clock:clock"])     # cart.h includes clock.h
c_test(name = "cart_test", srcs = ["tests/cart_test.c"],
       deps = [":cart", "//apps/shop/contracts/clock:fake"])         # the fake, never the real `pay`
```
The product files, in full:
```toml
# products/shop/decoupling.toml
[modules]
contract    = ["//apps/shop/contracts/**"]
component   = ["//apps/shop/parts/**"]
composition = ["//apps/shop/main:*"]
fake        = ["//apps/shop/contracts/clock:fake"]
[tests]
integration = ["//apps/shop/itest/**"]
```
A clean product needs no baseline file. An existing one adopts each rule by declaring what the rule reads:
`unused-dep` and the export rules need only the (possibly empty) `decoupling.toml`; the test rules need `component`
(and `[tests]` once a module-less test package exists); `contract-has-behaviour` and `interface-changed` need
`contract` (or `frozen`). Then: grade the main branch once, run the tool with that grade's facts, commit the output
as the baseline, pin the gate. From then on the list only shrinks.

## What the gate cannot see
* **Includes are read from the text**, not from the preprocessor: an `#include` under `#if 0` counts as a use, an
  include whose operand is a macro is not seen, and a header reached only through another header is not a use (that
  is the rule: include what you use).
* **Symbols are what the release objects reference.** A dependency used only through a macro or a `static inline`
  function of its header shows as an include or not at all; one used only for types is used by its include alone. A
  call the optimiser removed leaves no symbol. A function pointer taken from a dep is a symbol reference and counts.
* **Generated sources** (`c_catalog`, `c_embed`) are not judged as targets; their header is `<package>/<name>.h` for
  the targets that include it.
* **Frozen headers are compared as text.** A reformatted declaration is a changed one (the safe side). What a frozen
  header takes from another module's header is not followed (that module is judged where it is frozen), and a meaning
  that changes without the text changing (a documented contract, the size of a type defined elsewhere) is invisible.
  An enumerator appended at the end is reported as a change: whether a consumer switches over the enum cannot be
  seen from here, so that too is a new version.
* **The link closure is the declared one.** It is what the build links, not what the test calls; a test that lists a
  component it never calls is an `unused-dep` first.
* **Kinds are declarations.** A component left out of `component` is free. The file is gate-owned for that reason.

## Files
`gate/rigor_lib/decoupling_config.py` (the declarations), `decoupling_scan.py` (text scans), `decoupling_model.py`
(targets and includes of a tree), `decoupling_rules.py` (violations), `decoupling_baseline.py` (the ratchet),
`decoupling_iface.py` (frozen headers), `grade_decoupling.py` (the gate), `gate/tools/decoupling.py` (the tool).
Unit tests: `gate/tests/test_decoupling.py`, `test_decoupling_iface.py`, `test_grade_decoupling.py`. Canaries:
`canaries/decoupling-*` ([canaries.md](canaries.md)).
