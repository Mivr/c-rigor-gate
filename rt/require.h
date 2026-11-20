/* rigor_require(cond): a guard. Evaluates `cond` exactly once; when it is false the process stops with
 * __builtin_trap(), in every build mode. It has no other effect: no message, no handler, no way to turn it
 * off, no variant that returns. See docs/require.md for what a guard is and what it is not.
 *
 * It is a function so that `cond` is ordinary product code (a test can kill its mutants) and the trap is the
 * gate's, not the product's. Gate-owned: a product that reaches for __builtin_trap itself is judged as before. */
#ifndef RIGOR_RT_REQUIRE_H
#define RIGOR_RT_REQUIRE_H

static inline __attribute__((always_inline)) void rigor_require(_Bool cond) {
    if (!cond) {
        __builtin_trap();
    }
}

#endif
