#include "sim/inv/events.h"

static const events_inv_t RULE_INV[EV_R_COUNT] = {
    0,     EV_I1,  EV_I1,  EV_I1,  EV_I1,  EV_I1,  EV_I1,  EV_I1,  EV_I2,  EV_I2,  EV_I9,  EV_I9,
    EV_I9, EV_I9,  EV_I9,  EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I10, EV_I15, EV_I15, EV_I15};

static const char *const RULE_NAME[EV_R_COUNT] = {
    "",
    "no-authorisation",
    "open-overlap",
    "corr-reused",
    "bad-payload",
    "handover-without-effect",
    "pulse-without-open",
    "extra-pulse",
    "not-durable",
    "book-undecodable",
    "crash-book-changed",
    "crash-book-unreadable",
    "crash-audit-format",
    "crash-audit-gap",
    "open-before-boot",
    "audit-format",
    "audit-gap",
    "audit-bound",
    "door-without-assignment",
    "door-without-open",
    "short-locker",
    "locker-table-full",
    "stuck-phase",
    "no-recovery",
    "not-idle-at-end"};

events_inv_t events_rule_inv(events_rule_t rule) {
    return (unsigned)rule < (unsigned)EV_R_COUNT ? RULE_INV[rule] : (events_inv_t)0;
}

const char *events_inv_name(events_inv_t inv) {
    switch (inv) {
    case EV_I1:
        return "I1";
    case EV_I2:
        return "I2";
    case EV_I9:
        return "I9";
    case EV_I10:
        return "I10";
    case EV_I15:
        return "I15";
    default:
        return NULL;
    }
}

const char *events_rule_name(events_rule_t rule) {
    return (unsigned)rule >= 1U && (unsigned)rule < (unsigned)EV_R_COUNT ? RULE_NAME[rule] : NULL;
}
