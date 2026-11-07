set -eu
# A new L3 module whose tests check one trivial value per function and otherwise only "does not crash":
# most mutants change which node a walk ends on, and the test can only tell by dereferencing a node whose
# `value` is NULL. B31 / R003 G6: the mutants die, but mostly of a crash, not of a failed check.
mkdir -p chain
cat > chain/BUCK <<'EOF'
load("@gate//rules:c.bzl", "c_library", "c_test")

c_library(
    name = "chain",
    srcs = ["chain.c"],
    headers = ["chain.h"],
    visibility = ["PUBLIC"],
)

c_test(name = "chain_test", srcs = ["chain_test.c"], deps = [":chain"])
EOF
cat > chain/chain.h <<'EOF'
#ifndef CHAIN_H
#define CHAIN_H

typedef struct chain_node {
    const struct chain_node *next;
    const int *value;
} chain_node;

const chain_node *chain_nth(const chain_node *head, unsigned n);
const chain_node *chain_last(const chain_node *head);

#endif
EOF
cat > chain/chain.c <<'EOF'
#include "chain.h"

const chain_node *chain_nth(const chain_node *head, unsigned n) {
    while (n > 0 && head != 0) {
        head = head->next;
        n--;
    }
    return head;
}

const chain_node *chain_last(const chain_node *head) {
    while (head != 0 && head->next != 0) {
        head = head->next;
    }
    return head;
}
EOF
cat > chain/chain_test.c <<'EOF'
#include "chain.h"
#include "ctest/ctest.h"

static const int g_seven = 7;

/* Only the last node has a value; walking to any other node and reading it faults. */
static const chain_node g_c = {0, &g_seven};
static const chain_node g_b = {&g_c, 0};
static const chain_node g_a = {&g_b, 0};

static void touch(const chain_node *node) {
    volatile int sink = *node->value;
    (void)sink;
}

static void t_nth_trivial(ctest_t *t) {
    CHECK(t, chain_nth(&g_a, 0) == &g_a);
}

static void t_nth_no_crash(ctest_t *t) {
    touch(chain_nth(&g_a, 2));
    CHECK(t, 1);
}

static void t_last_trivial(ctest_t *t) {
    CHECK(t, chain_last(&g_c) == &g_c);
}

static void t_last_no_crash(ctest_t *t) {
    touch(chain_last(&g_a));
    CHECK(t, 1);
}

CTEST_SUITE("chain", { "nth", t_nth_trivial }, { "nth_no_crash", t_nth_no_crash }, { "last", t_last_trivial },
            { "last_no_crash", t_last_no_crash })
EOF
