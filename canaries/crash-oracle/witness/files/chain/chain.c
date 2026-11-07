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
