/* Runtime of the schema mutation engine (T124, docs/mutate-schema.md).
 *
 * A schema object holds every mutant of a source, switchable at run time: the generator wraps each mutated site in
 * `rigor_hit(N)`, which records that the site was executed (the reach bitmap) and says whether mutant N is the active
 * one. The test binary is linked once, with `-Wl,--wrap=main`; `__wrap_main` (schema_rt.c) runs the real main in one of
 * two modes, see schema_rt.c. Index 0 is "no mutant"; the generator numbers mutants from 1 and never goes past
 * RIGOR_SCHEMA_MAX - 1.
 */
#ifndef RIGOR_SCHEMA_RT_H
#define RIGOR_SCHEMA_RT_H

#define RIGOR_SCHEMA_MAX 131072

extern unsigned char *rigor_reach; /* byte N is set once the site of mutant N has run (shared memory in reach mode) */
extern int rigor_active;           /* the active mutant, 0 for none */

static inline int rigor_hit(int n) {
    rigor_reach[n] = 1;
    return rigor_active == n;
}

#endif
