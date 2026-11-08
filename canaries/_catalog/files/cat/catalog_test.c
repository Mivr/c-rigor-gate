#include "cat/catalog.h"
#include "ctest/ctest.h"
#include "i18n/i18n.h"

static void check(ctest_t *t, uint8_t lang, uint16_t id, const i18n_arg_t *a, uint8_t n, const char *want)
{
    char out[64];
    CHECK_EQ_I64(t, i18n_format(&cv_catalog, lang, id, a, n, out, sizeof out), 0);
    CHECK_EQ_STR(t, out, want);
}

static void t_bg(ctest_t *t)
{
    const i18n_arg_t one[1] = {{I18N_INT, 7, NULL}};
    const i18n_arg_t two[2] = {{I18N_INT, 3, NULL}, {I18N_INT, 10, NULL}};
    check(t, 0, CV_CATALOG_HELLO, NULL, 0, "\320\227\320\264\321\200\320\260\320\262\320\265\320\271");
    check(t, 0, CV_CATALOG_HELLO_BANG, NULL, 0, "Zdrasti");
    check(t, 0, CV_CATALOG_LOCKER_0, one, 1, "Shkafche 7");
    check(t, 0, CV_CATALOG_OPEN_0_OF_1, two, 2, "Otvoreno 10 ot 3");
}

static void t_en(ctest_t *t)
{
    const i18n_arg_t one[1] = {{I18N_INT, -7, NULL}};
    const i18n_arg_t two[2] = {{I18N_INT, 3, NULL}, {I18N_INT, 10, NULL}};
    check(t, 1, CV_CATALOG_HELLO, NULL, 0, "Hello");
    check(t, 1, CV_CATALOG_HELLO_BANG, NULL, 0, "hello!");
    check(t, 1, CV_CATALOG_LOCKER_0, one, 1, "Locker -7");
    check(t, 1, CV_CATALOG_OPEN_0_OF_1, two, 2, "Open 3 of 10");
    CHECK_EQ_I64(t, CV_CATALOG__COUNT, 4);
}

CTEST_SUITE("catalog", { "bg", t_bg }, { "en", t_en })
