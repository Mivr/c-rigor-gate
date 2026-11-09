/* ctest: a tiny test framework whose results cannot be faked from inside a test.
 *
 * A test is `static void t_<name>(ctest_t *t)`. Tests are registered in an explicit table:
 *
 *     CTEST_SUITE("suite",
 *         { "name", t_name },
 *         { "other", t_other })
 *
 * which defines main(). Every test runs in its own forked child with a fixed 10 s timeout.
 * The child holds no file descriptor of ours: it reports through anonymous shared memory and the
 * results file is opened only after all children are gone.
 * A test passes only if its child reported its check counts back to the parent, executed at
 * least one check, had no failed check and exited with status 0. There is no skip and no
 * expected-failure. Results are JSON Lines, see docs/ctest.md.
 *
 * Usage: <test-binary> [--seed N] [--out FILE] [--san-log PREFIX --san-report FILE]
 *        (exit 0: all passed, 1: a test failed, 2: error). See docs/ctest.md for the sanitizer options.
 */
#ifndef CTEST_H
#define CTEST_H

#include <stddef.h>
#include <stdint.h>

typedef struct ctest ctest_t;
typedef void (*ctest_fn)(ctest_t *t);
typedef struct {
    const char *name; /* [a-z0-9_]+, unique within the suite */
    ctest_fn fn;
} ctest_case_t;

void ctest_check(ctest_t *t, int ok, const char *file, int line, const char *expr);
void ctest_check_i64(ctest_t *t, int64_t a, int64_t b, const char *file, int line, const char *ea,
                     const char *eb);
void ctest_check_u64(ctest_t *t, uint64_t a, uint64_t b, const char *file, int line, const char *ea,
                     const char *eb);
void ctest_check_str(ctest_t *t, const char *a, const char *b, const char *file, int line,
                     const char *ea, const char *eb);
void ctest_check_mem(ctest_t *t, const void *a, size_t alen, const void *b, size_t blen,
                     const char *file, int line, const char *ea, const char *eb);

/* CHECK_TRAPS support (docs/ctest.md): `ctest_trap_begin` forks. In the child it returns 1: the macro then evaluates
 * the expression and calls `ctest_trap_returned`. In the parent it waits for the child, counts one check and
 * returns 0. The check passes only if the child died by SIGILL, the signal of __builtin_trap(). */
int ctest_trap_begin(ctest_t *t, const char *file, int line, const char *expr);
_Noreturn void ctest_trap_returned(void);

int ctest_run(int argc, char **argv, const char *suite, const ctest_case_t *cases, size_t n);

/* Each check counts as one assertion; a failed check is recorded and the test continues. */
#define CHECK(t, cond) ctest_check((t), (cond) ? 1 : 0, __FILE__, __LINE__, #cond)
#define CHECK_EQ_I64(t, a, b) \
    ctest_check_i64((t), (int64_t)(a), (int64_t)(b), __FILE__, __LINE__, #a, #b)
#define CHECK_EQ_U64(t, a, b) \
    ctest_check_u64((t), (uint64_t)(a), (uint64_t)(b), __FILE__, __LINE__, #a, #b)
#define CHECK_EQ_STR(t, a, b) ctest_check_str((t), (a), (b), __FILE__, __LINE__, #a, #b)
#define CHECK_EQ_MEM(t, a, alen, b, blen) \
    ctest_check_mem((t), (a), (alen), (b), (blen), __FILE__, __LINE__, #a, #b)

/* The expression runs in a child process and must die by the trap of rigor_require (rt/require.h): it fails when
 * the expression returns, when the child exits, or when it dies any other way. One check. A trap outside this
 * macro kills the test as before. */
#define CHECK_TRAPS(t, expression)                                              \
    do {                                                                        \
        if (ctest_trap_begin((t), __FILE__, __LINE__, #expression) != 0) {      \
            (void)(expression);                                                 \
            ctest_trap_returned();                                              \
        }                                                                       \
    } while (0)

#define CTEST_SUITE(suite_name, ...)                                                        \
    int main(int argc, char **argv) {                                                       \
        static const ctest_case_t ctest_cases_[] = {__VA_ARGS__};                           \
        return ctest_run(argc, argv, (suite_name), ctest_cases_,                            \
                         sizeof ctest_cases_ / sizeof ctest_cases_[0]);                     \
    }

#endif
