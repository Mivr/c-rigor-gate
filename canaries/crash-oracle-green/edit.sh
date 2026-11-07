set -eu
# Green twin of crash-oracle: the same module with real assertions on every result, so no function is
# killed mostly by crashes. Must PASS every gate (B31).
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
const chain_node *chain_skip(const chain_node *head, unsigned n);

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

const chain_node *chain_skip(const chain_node *head, unsigned n) {
    unsigned left = n;
    while (left != 0 && head != 0) {
        head = head->next;
        left = left - 1;
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

static const chain_node g_c = {0, &g_seven};
static const chain_node g_b = {&g_c, 0};
static const chain_node g_a = {&g_b, 0};

static void t_nth(ctest_t *t) {
    CHECK(t, chain_nth(&g_a, 0) == &g_a);
    CHECK(t, chain_nth(&g_a, 1) == &g_b);
    CHECK(t, chain_nth(&g_a, 2) == &g_c);
    CHECK(t, chain_nth(&g_a, 3) == 0);
    CHECK(t, chain_nth(&g_a, 9) == 0);
    CHECK(t, chain_nth(0, 0) == 0);
}

static void t_skip(ctest_t *t) {
    CHECK(t, chain_skip(&g_a, 0) == &g_a);
    CHECK(t, chain_skip(&g_a, 1) == &g_b);
    CHECK(t, chain_skip(&g_a, 2) == &g_c);
    CHECK(t, chain_skip(&g_a, 3) == 0);
    CHECK(t, chain_skip(&g_a, 9) == 0);
    CHECK(t, chain_skip(0, 0) == 0);
}

static void t_last(ctest_t *t) {
    CHECK(t, chain_last(&g_a) == &g_c);
    CHECK(t, chain_last(&g_b) == &g_c);
    CHECK(t, chain_last(&g_c) == &g_c);
    CHECK(t, chain_last(0) == 0);
}

CTEST_SUITE("chain", { "nth", t_nth }, { "skip", t_skip }, { "last", t_last })
EOF
