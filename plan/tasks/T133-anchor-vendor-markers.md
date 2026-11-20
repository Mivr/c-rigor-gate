# T133: a product directory must not be able to pass as gate-owned third-party code (anchor the vendor markers)

Repo: `Mivr/c-rigor-gate`. Branch `task/T133` from main. Read `gate/rigor_lib/cscan.py` (`Collector.is_system`,
`vendor_markers`, and `output_tree` / `is_gate_path` once T131 is merged; if they are not on your base yet, write the
same anchored path walk and say so), `rules/facts.bzl` and `rules/third_party.bzl` (where the markers come from),
`docs/third-party.md`, `docs/product-checks.md` ("Line markers", "Known limits"), `gate/rigor_lib/product_layout.py`,
`mutate/gen.py` and `gate/rigor_lib/structure_scan.py` (how each decides that a file is not product code).

## Why (found while reviewing T131, not yet demonstrated)
The semantic scanner treats a file as vendored, and skips its text entirely, when the path the compiler read contains
a vendor marker such as `/art/<gate cell>/third_party/` **anywhere** (`any(m in norm for m in self.vendor)`). A product
that names a directory `x/art/gate/third_party/` gets header trees under
`buck-out/v2/art/root/x/art/gate/third_party/...`, which contain the marker. A header there could then carry a
diagnostic pragma, `__attribute__((no_sanitize))`, inline assembly or a banned builtin, and the `semantic-suppressions`
gate would not see it. T131 closed the same mistake for the gate's own `rt/require.h`.

## Do
1. **Demonstrate it first.** Build a small product with such a directory and a header that carries (a) a
   `#pragma clang diagnostic ignored`, (b) `__attribute__((no_sanitize("address")))` on a function, and run the facts
   and the semantic judgement on it. Report exactly what today's code does. If the spoof does **not** work, say what
   stops it, keep the test as a regression case, and do steps 2 and 4 anyway where a substring match exists.
2. **Anchor every such decision.** A file is the gate's third-party code only when the compiler read it from the
   output tree of a cell other than the product's, at the path the gate's own third-party rules produce; never
   because a fragment appears somewhere in a path. One function decides it for the scanner. Then check, by reading
   and with a test each, the other places that decide "not product code" from a path: `mutate/gen.py` (unmutated
   headers of another cell), `gate/rigor_lib/structure_scan.py` (files not reported), and anything in
   `gate/rigor_lib/facts_*.py`. Fix any that match a fragment anywhere; list each one in your report with its verdict.
   An unrecognised layout is product code.
3. **The gate's own selftests.** There the gate is the root cell. Keep them working with an anchored marker that
   starts right after the output kind, as T131 did for `rt/require.h`.
4. **A canary** `vendor-path-spoof`: the product of step 1; it must be red on `semantic-suppressions`. Follow
   `docs/canaries.md`. Add unit tests for the path decision: the real third-party tree in a product grade, the same
   when the gate is the root cell, the spoofed product path, and a path with no recognisable layout.
5. **Docs.** `docs/third-party.md` and `docs/product-checks.md`: the rule, and the sentence that a directory of that
   name in a product is not exempt must now be true for every checker.

## Not in this task
Any change to what is allowed inside real third-party code; `products/**`; `gate/rigor_lib/grade*.py`.

## Acceptance
`python3 -I -B gate/tests/run_parallel.py`; `selftest/product_checks.sh`; `selftest/third_party.sh`;
`selftest/structure.sh`; `selftest/mutate.sh`; `selftest/canaries.sh --jobs 8` (the new canary red, no other change);
`selftest/tripwires.sh --jobs 5`; `python3 -I tools/affected.py --check`.

## Allowed paths
`gate/rigor_lib/cscan.py`, `gate/rigor_lib/facts_*.py`, `gate/rigor_lib/structure_scan.py`, `mutate/gen.py` (the path
decision only), `rules/facts.bzl`, `rules/third_party.bzl`, `rules/structure.bzl`, `rules/mutate.bzl` (marker arguments
only), `gate/tests/**`, `canaries/vendor-path-spoof/**` and the canary catalogue files, `selftest/third_party.sh`,
`selftest/third_party/**`, `docs/third-party.md`, `docs/product-checks.md`, `docs/canaries.md`, `tools/affected.toml`.

## Rules
Worktree `/var/tmp/wt/c-rigor-gate/T133`. `TMPDIR=/var/tmp/cache/T133/tmp`; never `/tmp`. Long runs via `tools/job`.
Redirect every output to a file and read it; never pipe into tail/head. Never `rm`. No stash, merge or push. **Never
use the Agent tool.** Never read `/var/tmp/.config`, `/var/tmp/.claude*`, `/var/tmp/src`, other worktrees or other
cache dirs; never search from `/` or `/var/tmp`. Do not print the environment. Kill only your own buck2d by pid. One
buck2 build at a time. No network except Buck2's pinned downloads. Never end your turn while a job you started is
running. If you need a throwaway script, write it with the Write tool or a heredoc so its text is in your transcript.
`rigor grade` and the canary runner refuse a dirty checkout: commit before you run them. Commit on `task/T133`; your
last message is the report (what the spoof did before and after, each path decision you checked, every deviation).
