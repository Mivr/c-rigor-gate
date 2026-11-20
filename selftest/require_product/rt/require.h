/* A product's own header with the name of the gate's: it carries a trap of its own. Nothing about it is the gate's,
 * so the trap is judged like any other product trap, whatever the target depends on. */
#ifndef OWN_RT_REQUIRE_H
#define OWN_RT_REQUIRE_H

static inline void own_require(int cond) {
    if (!cond) {
        __builtin_trap();
    }
}

#endif
