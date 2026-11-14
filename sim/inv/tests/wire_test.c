/* Wire invariants: the feed contract, the I6b allow-list, the frame-level I3/I4 rules, coil reads, the board cross-check. */
#include <string.h>

#include "sim/inv/tests/rig.h"

#define N(a) (sizeof(a))

/* The whole mask of one frame fed to a fresh engine. */
static uint32_t mask_of(ctest_t *t, const uint8_t *body, size_t n) {
    static rig_t r;
    rig_init(&r, t);
    rig_frame(&r, 100, 0, body, n);
    return wire_inv_mask(&r.w);
}

#define BIT(inv) (1U << (unsigned)(inv))

static void t_feed_contract(ctest_t *t) {
    static wire_t w;
    wire_init(&w);
    uint8_t body[] = {1, 1, 0, 0, 0, 30, 0xbc, 0x02};
    sim_rec_t ev = {{'e', 'v'}, 5, 0, 0, NULL, 0};
    CHECK_EQ_I64(t, wire_feed(&w, &ev), 1);
    CHECK_EQ_U64(t, w.records, 0);
    sim_rec_t fx = {{'f', 'x'}, 5, 0, 0, NULL, 0};
    CHECK_EQ_I64(t, wire_feed(&w, &fx), 1);
    sim_rec_t ef = {{'e', 'r'}, 5, 0, 0, NULL, 0};
    CHECK_EQ_I64(t, wire_feed(&w, &ef), 1);
    sim_rec_t fr = {{'f', 'r'}, 100, 0, 0, body, sizeof body};
    CHECK_EQ_I64(t, wire_feed(&w, &fr), 0);
    CHECK_EQ_U64(t, w.records, 1);
    fr.t_ms = 100;
    CHECK_EQ_I64(t, wire_feed(&w, &fr), 0); /* the same time is not backwards */
    fr.t_ms = 99;
    CHECK_EQ_I64(t, wire_feed(&w, &fr), -1);
    CHECK_EQ_U64(t, w.records, 2);
    CHECK_EQ_U64(t, w.now, 100);
    sim_rec_t dir2 = {{'f', 'r'}, 200, 2, 0, body, sizeof body};
    CHECK_EQ_I64(t, wire_feed(&w, &dir2), -1);
    sim_rec_t nobytes = {{'f', 'r'}, 200, 0, 0, NULL, 8};
    CHECK_EQ_I64(t, wire_feed(&w, &nobytes), -1);
    nobytes.len = 1;
    CHECK_EQ_I64(t, wire_feed(&w, &nobytes), -1);
    CHECK_EQ_I64(t, wire_feed(&w, NULL), -1);
    CHECK_EQ_I64(t, wire_feed(NULL, &fr), -1);
    CHECK_EQ_U64(t, w.records, 2);
    sim_rec_t empty = {{'f', 'r'}, 200, 0, 0, NULL, 0}; /* an empty frame is a frame: no CRC, so I6b */
    CHECK_EQ_I64(t, wire_feed(&w, &empty), 0);
    CHECK(t, wire_has_inv(&w, WIRE_I6B));
    CHECK_EQ_I64(t, wire_finish(&w, 199), -1);
    CHECK_EQ_I64(t, wire_finish(NULL, 300), -1);
    CHECK_EQ_I64(t, wire_finish(&w, 200), 0);
    CHECK_EQ_I64(t, wire_finish(&w, 300), 0);
    CHECK_EQ_U64(t, w.now, 300);
}

static void t_allow_list(ctest_t *t) {
    static const uint8_t ok[][6] = {
        {1, 1, 0, 0, 0, 30},          /* read all 30 coils */
        {1, 1, 0, 0, 0, 1},           /* read coil 0 */
        {1, 1, 0, 29, 0, 1},          /* read coil 29 */
        {1, 3, 0x80, 0x00, 0, 1},     /* version */
        {1, 3, 0x40, 0x00, 0, 1},     /* device parameter */
        {1, 5, 0x02, 0x00, 0, 1},     /* flash 1 unit, channel 0 */
        {1, 5, 0x02, 0x00, 0, 8},     /* flash 8 units */
        {1, 5, 0x02, 0x1d, 0, 3},     /* flash, channel 29 */
        {1, 5, 0x00, 0xff, 0, 0},     /* all off */
    };
    for (size_t i = 0; i < N(ok) / N(ok[0]); i++) {
        CHECK(t, (mask_of(t, ok[i], N(ok[i])) & BIT(WIRE_I6B)) == 0U);
    }
    static const uint8_t bad[][6] = {
        {2, 1, 0, 0, 0, 30},          /* another slave */
        {0, 1, 0, 0, 0, 30},          /* broadcast */
        {1, 1, 0, 0, 0, 0},           /* zero coils */
        {1, 1, 0, 0, 0, 31},          /* 31 coils */
        {1, 1, 0, 1, 0, 30},          /* runs past coil 29 */
        {1, 1, 0, 29, 0, 2},          /* runs past coil 29 */
        {1, 1, 0, 30, 0, 1},          /* starts past coil 29 */
        {1, 3, 0x80, 0x00, 0, 2},     /* two registers */
        {1, 3, 0x80, 0x01, 0, 1},     /* another register */
        {1, 3, 0x40, 0x01, 0, 1},
        {1, 3, 0x00, 0x00, 0, 1},
        {1, 5, 0x02, 0x1e, 0, 3},     /* flash beyond channel 29 */
        {1, 5, 0x01, 0xff, 0, 3},     /* below the flash range */
        {1, 5, 0x02, 0x00, 0, 9},     /* 9 units */
        {1, 5, 0x02, 0x00, 0, 0},     /* 0 units */
        {1, 5, 0x00, 0x03, 0, 0},     /* a single coil off */
        {1, 5, 0x00, 0xff, 0, 1},     /* all-off address with another value */
        {1, 5, 0x00, 0xff, 0xff, 0},  /* all coils, value 0xff00: ON */
        {1, 6, 0x00, 0x00, 0, 1},     /* another function */
    };
    for (size_t i = 0; i < N(bad) / N(bad[0]); i++) {
        CHECK(t, (mask_of(t, bad[i], N(bad[i])) & BIT(WIRE_I6B)) != 0U);
    }
}

static void t_bad_crc_and_short_frames(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    uint8_t good[] = {1, 1, 0, 0, 0, 30, 0xbc, 0x02};
    rig_raw(&r, 1, 0, good, sizeof good);
    CHECK_EQ_U64(t, wire_inv_mask(&r.w), 0);
    good[7] ^= 1U;
    rig_raw(&r, 2, 0, good, sizeof good);
    CHECK_EQ_U64(t, wire_inv_mask(&r.w), BIT(WIRE_I6B));
    CHECK(t, rig_rule(&r, WIRE_R_UNSAFE_FRAME));
    rig_init(&r, t);
    rig_raw(&r, 1, 0, good, 3);
    CHECK(t, wire_has_inv(&r.w, WIRE_I6B));
}

static void t_on_frames_are_i3(ctest_t *t) {
    static const uint8_t on_coil[] = {1, 5, 0x00, 0x00, 0xff, 0x00};
    static const uint8_t on_flash_addr[] = {1, 5, 0x02, 0x0c, 0xff, 0x00};
    static const uint8_t toggle[] = {1, 5, 0x00, 0x05, 0x55, 0x00};
    static const uint8_t all_on[] = {1, 5, 0x00, 0xff, 0xff, 0x00};
    CHECK_EQ_U64(t, mask_of(t, on_coil, N(on_coil)), BIT(WIRE_I3) | BIT(WIRE_I6B));
    CHECK_EQ_U64(t, mask_of(t, on_flash_addr, N(on_flash_addr)), BIT(WIRE_I3) | BIT(WIRE_I6B));
    CHECK_EQ_U64(t, mask_of(t, toggle, N(toggle)), BIT(WIRE_I3) | BIT(WIRE_I6B));
    CHECK_EQ_U64(t, mask_of(t, all_on, N(all_on)), BIT(WIRE_I3) | BIT(WIRE_I6B));
    static rig_t r;
    rig_init(&r, t);
    rig_raw(&r, 1, 0, all_on, 0); /* an empty frame: nothing to model */
    rig_init(&r, t);
    rig_write(&r, 1, 0x00ff, 0xff00);
    CHECK(t, rig_rule(&r, WIRE_R_ON_FRAME));
    CHECK(t, rig_rule(&r, WIRE_R_TWO_ENERGISED)); /* all 30 coils are on in the model */
    CHECK(t, !rig_rule(&r, WIRE_R_UNITS));
}

static void t_write_coils_frame(ctest_t *t) {
    /* FC0F with a set bit is I3; with all bits clear it is only outside the allow-list. */
    static const uint8_t set[] = {1, 0x0f, 0, 2, 0, 3, 1, 0x05};
    static const uint8_t clear[] = {1, 0x0f, 0, 2, 0, 3, 1, 0x00};
    CHECK_EQ_U64(t, mask_of(t, set, N(set)), BIT(WIRE_I3) | BIT(WIRE_I6B));
    CHECK_EQ_U64(t, mask_of(t, clear, N(clear)), BIT(WIRE_I6B));
    /* ON coil 3, then FC0F: coils 2 and 4 on, coil 3 off: two coils on, not three. */
    static rig_t r;
    rig_init(&r, t);
    rig_write(&r, 1, 3, 0xff00);
    rig_frame(&r, 2, 0, set, sizeof set);
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
    CHECK_EQ_U64(t, rig_rule_count(&r, WIRE_R_ON_FRAME), 2);
    /* Three on at once. */
    rig_init(&r, t);
    rig_write(&r, 1, 3, 0xff00);
    rig_write(&r, 2, 4, 0xff00);
    rig_write(&r, 3, 5, 0xff00);
    CHECK(t, rig_rule(&r, WIRE_R_TWO_ENERGISED));
    /* FC0F reaching the end of the board stops at coil 29. */
    static const uint8_t edge[] = {1, 0x0f, 0, 28, 0, 5, 1, 0x1f};
    rig_init(&r, t);
    rig_frame(&r, 1, 0, edge, sizeof edge);
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
    CHECK_EQ_U64(t, r.w.coil[28].on, 1);
    CHECK_EQ_U64(t, r.w.coil[29].on, 1);
}

static void t_plain_on_burns(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    rig_write(&r, 0, 3, 0xff00);
    CHECK_EQ_I64(t, wire_finish(&r.w, 999), 0);
    CHECK(t, !rig_rule(&r, WIRE_R_BURN));
    CHECK_EQ_I64(t, wire_finish(&r.w, 1000), 0);
    CHECK(t, rig_rule(&r, WIRE_R_BURN));
    CHECK_EQ_U64(t, rig_rule_count(&r, WIRE_R_BURN), 1);
    CHECK_EQ_I64(t, wire_finish(&r.w, 5000), 0);
    CHECK_EQ_U64(t, rig_rule_count(&r, WIRE_R_BURN), 1); /* once per chain */
}

static void t_units_are_i4(ctest_t *t) {
    static rig_t r;
    for (unsigned units = 0; units <= 10U; units++) {
        rig_init(&r, t);
        rig_flash(&r, 5, 3, (uint16_t)units);
        int bad = units < 1U || units > 8U;
        CHECK_EQ_I64(t, wire_has_rule(&r.w, WIRE_R_UNITS), bad);
        CHECK_EQ_I64(t, wire_has_inv(&r.w, WIRE_I4), bad);
        CHECK_EQ_I64(t, wire_has_inv(&r.w, WIRE_I6B), bad);
        CHECK_EQ_I64(t, wire_has_inv(&r.w, WIRE_I3), 0);
    }
    rig_init(&r, t);
    rig_flash(&r, 5, 3, 0x0100);
    CHECK(t, rig_rule(&r, WIRE_R_UNITS));
    rig_init(&r, t);
    rig_flash(&r, 5, 3, 9);
    CHECK_EQ_U64(t, wire_inv_mask(&r.w), BIT(WIRE_I4) | BIT(WIRE_I6B));
    CHECK_EQ_U64(t, r.w.coil[3].on, 0); /* a refused flash is not modelled */
}

/* A response is matched to the request before it, and only a good coil read with the right byte count counts. */
static void t_responses_are_matched(ctest_t *t) {
    static const uint8_t req[] = {1, 1, 0, 0, 0, 30};
    static const uint8_t off4[] = {1, 1, 4, 0, 0, 0, 0};
    static const uint8_t off3[] = {1, 1, 3, 0, 0, 0};
    static const uint8_t reg[] = {1, 3, 2, 0, 0x64};
    static rig_t r;
    /* No request first: nothing is learned, so the flash has no pre-read. */
    rig_init(&r, t);
    rig_frame(&r, 1, 1, off4, sizeof off4);
    rig_flash(&r, 2, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* A bad CRC answer. */
    rig_init(&r, t);
    rig_frame(&r, 1, 0, req, sizeof req);
    uint8_t bad[9] = {1, 1, 4, 0, 0, 0, 0, 0, 0};
    rig_raw(&r, 2, 1, bad, sizeof bad);
    rig_flash(&r, 3, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* The wrong byte count. */
    rig_init(&r, t);
    rig_frame(&r, 1, 0, req, sizeof req);
    rig_frame(&r, 2, 1, off3, sizeof off3);
    rig_flash(&r, 3, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* The answer of another function. */
    rig_init(&r, t);
    rig_frame(&r, 1, 0, req, sizeof req);
    rig_frame(&r, 2, 1, reg, sizeof reg);
    rig_flash(&r, 3, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* A read request that is not a coil read, answered with coils. */
    static const uint8_t version[] = {1, 3, 0x80, 0, 0, 1};
    rig_init(&r, t);
    rig_frame(&r, 1, 0, version, sizeof version);
    rig_frame(&r, 2, 1, off4, sizeof off4);
    rig_flash(&r, 3, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* The same exchange done right. */
    rig_init(&r, t);
    rig_frame(&r, 1, 0, req, sizeof req);
    rig_frame(&r, 2, 1, off4, sizeof off4);
    rig_flash(&r, 3, 1, 5);
    CHECK_EQ_U64(t, wire_inv_mask(&r.w), 0);
    /* One answer answers one request: a second answer does not count. */
    rig_init(&r, t);
    rig_frame(&r, 1, 0, req, sizeof req);
    rig_frame(&r, 2, 1, reg, sizeof reg);
    rig_frame(&r, 3, 1, off4, sizeof off4);
    rig_flash(&r, 4, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    /* A request that is not allowed is not answered by a read: a read of 31 coils. */
    static const uint8_t big[] = {1, 1, 0, 0, 0, 31};
    static const uint8_t off4b[] = {1, 1, 4, 0, 0, 0, 0};
    rig_init(&r, t);
    rig_frame(&r, 1, 0, big, sizeof big);
    rig_frame(&r, 2, 1, off4b, sizeof off4b);
    rig_flash(&r, 3, 1, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
}

static void t_partial_reads_and_masks(ctest_t *t) {
    static rig_t r;
    /* Coil 12 stuck on; a read of coils 0..7 showing off does not clear it, a read covering coil 12 does. */
    for (int covering = 0; covering <= 1; covering++) {
        rig_init(&r, t);
        rig_read(&r, 0, 0);
        rig_flash(&r, 10, 12, 5);
        rig_read(&r, 700, 1U << 12); /* past the latest off time: stuck */
        if (covering != 0) {
            rig_read_part(&r, 800, 8, 8, 0);
        } else {
            rig_read_part(&r, 800, 0, 8, 0);
        }
        CHECK_EQ_I64(t, wire_finish(&r.w, 1010), 0);
        CHECK_EQ_I64(t, rig_rule(&r, WIRE_R_BURN), covering == 0);
    }
    /* Data bits past the quantity are ignored: coils 30 and 31 of a 30-coil answer. */
    static const uint32_t top[] = {0x00000000U, 0x40000000U, 0x80000000U, 0xc0000000U};
    for (size_t k = 0; k < N(top) / N(top[0]); k++) {
        uint32_t bits = top[k];
        rig_init(&r, t);
        rig_read(&r, 0, 0);
        rig_flash(&r, 1000, 1, 5);
        rig_read(&r, 1100, bits);
        CHECK_EQ_I64(t, wire_finish(&r.w, 2100), 0);
        CHECK_EQ_I64(t, rig_rule(&r, WIRE_R_VERIFY_LATE), 0);
    }
    /* A short read: bits past its quantity are ignored, and it is no verify read. */
    rig_init(&r, t);
    rig_read(&r, 0, 0);
    rig_flash(&r, 1000, 1, 5);
    rig_read_part(&r, 1100, 0, 2, 0xfc);
    CHECK_EQ_I64(t, wire_finish(&r.w, 2100), 0);
    CHECK(t, rig_rule(&r, WIRE_R_VERIFY_LATE));
    CHECK_EQ_U64(t, r.w.coil[2].on, 0);
    CHECK_EQ_U64(t, r.w.coil[1].on, 0); /* the read says coil 1 is off: reads are authoritative */
}

static void t_findings_are_recorded(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    uint8_t bad[] = {1, 1, 0, 0, 0, 30, 0, 0};
    for (uint64_t i = 0; i < 20U; i++) {
        rig_raw(&r, 100U + i, 0, bad, sizeof bad);
    }
    CHECK_EQ_U64(t, wire_finding_count(&r.w), 20);
    const wire_finding_t *f = wire_finding(&r.w, 15);
    CHECK(t, f != NULL);
    if (f != NULL) {
        CHECK_EQ_I64(t, f->inv, WIRE_I6B);
        CHECK_EQ_I64(t, f->rule, WIRE_R_UNSAFE_FRAME);
        CHECK_EQ_U64(t, f->t_ms, 115);
        CHECK_EQ_U64(t, f->record, 15);
    }
    CHECK(t, wire_finding(&r.w, 16) == NULL);
    CHECK(t, wire_finding(&r.w, 19) == NULL);
    CHECK(t, wire_finding(&r.w, 0) != NULL);
    CHECK_EQ_U64(t, r.w.dropped, 4);
    CHECK_EQ_U64(t, wire_finding_count(&r.w) - r.w.dropped, WIRE_MAX_FINDINGS);
}

static void t_crosscheck(ctest_t *t) {
    static rig_t clean;
    rig_init(&clean, t);
    CHECK_EQ_I64(t, wire_crosscheck(&clean.w, 0), WIRE_XC_AGREE);
    CHECK_EQ_I64(t, wire_crosscheck(&clean.w, 1), WIRE_XC_BOARD_ONLY);
    CHECK_EQ_I64(t, wire_crosscheck(&clean.w, 7), WIRE_XC_BOARD_ONLY);
    /* Each rule the board can see. */
    static rig_t r;
    rig_init(&r, t);
    rig_write(&r, 1, 3, 0xff00);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_ENGINE_ONLY);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 2), WIRE_XC_AGREE);
    rig_init(&r, t);
    rig_flash(&r, 1, 3, 9);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_ENGINE_ONLY);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 1), WIRE_XC_AGREE);
    rig_init(&r, t);
    rig_write(&r, 1, 3, 0xff00);
    rig_write(&r, 2, 4, 0xff00);
    rig_write(&r, 3, 5, 0xff00);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 1), WIRE_XC_AGREE);
    rig_init(&r, t);
    rig_write(&r, 0, 3, 0xff00);
    CHECK_EQ_I64(t, wire_finish(&r.w, 1000), 0);
    CHECK(t, rig_rule(&r, WIRE_R_BURN));
    /* Only the engine's own rules (allow-list, read-off, gap, watchdog): the board has nothing to say. */
    rig_init(&r, t);
    static const uint8_t other[] = {1, 6, 0, 0, 0, 1};
    rig_frame(&r, 1, 0, other, sizeof other);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_AGREE);
    rig_init(&r, t);
    rig_flash(&r, 1, 3, 5);
    CHECK(t, rig_rule(&r, WIRE_R_NO_PREREAD));
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_AGREE);
}


static void t_on_frames_set_the_model(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    rig_write(&r, 1, 0x0200, 0xff00); /* ON at the flash address of channel 0 */
    CHECK_EQ_U64(t, r.w.coil[0].on, 1);
    CHECK_EQ_U64(t, r.w.coil[1].on, 0);
    rig_write(&r, 2, 0x020c, 0xff00);
    CHECK_EQ_U64(t, r.w.coil[12].on, 1);
    CHECK_EQ_U64(t, r.w.coil[0x20c & 0x1f].on, r.w.coil[12].on);
    rig_init(&r, t);
    rig_write(&r, 1, 0x00ff, 0xff00); /* all on */
    CHECK_EQ_U64(t, r.w.coil[0].on, 1);
    CHECK_EQ_U64(t, r.w.coil[29].on, 1);
    rig_alloff(&r, 2);
    CHECK_EQ_U64(t, r.w.coil[0].on, 0);
    CHECK_EQ_U64(t, r.w.coil[29].on, 0);
    CHECK_EQ_U64(t, r.w.coil[15].on, 0);
    /* An ON for a coil the board does not have names no coil. */
    rig_init(&r, t);
    rig_write(&r, 1, 30, 0xff00);
    rig_write(&r, 2, 0x0100, 0xff00);
    rig_write(&r, 3, 0x021e, 0xff00);
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
    CHECK_EQ_U64(t, rig_rule_count(&r, WIRE_R_ON_FRAME), 3);
}

static void t_single_coil_off(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    rig_write(&r, 1, 3, 0xff00);
    rig_write(&r, 2, 5, 0xff00);
    rig_write(&r, 3, 3, 0); /* coil 3 off, nothing else */
    CHECK_EQ_U64(t, r.w.coil[3].on, 0);
    CHECK_EQ_U64(t, r.w.coil[5].on, 1);
    CHECK(t, wire_has_inv(&r.w, WIRE_I6B));
    /* Not an off, not an all-off: other values and other addresses leave the model alone. */
    rig_write(&r, 4, 5, 1);
    rig_write(&r, 5, 0x00ff, 1);
    rig_write(&r, 6, 0x0100, 0);
    rig_write(&r, 7, 30, 0);
    CHECK_EQ_U64(t, r.w.coil[5].on, 1);
    /* The all-off address does clear it. */
    rig_alloff(&r, 8);
    CHECK_EQ_U64(t, r.w.coil[5].on, 0);
}

static void t_write_coils_model(ctest_t *t) {
    static rig_t r;
    /* One set bit is already an ON frame. */
    static const uint8_t one[] = {1, 0x0f, 0, 4, 0, 1, 1, 0x01};
    rig_init(&r, t);
    rig_frame(&r, 1, 0, one, sizeof one);
    CHECK(t, rig_rule(&r, WIRE_R_ON_FRAME));
    CHECK_EQ_U64(t, r.w.coil[4].on, 1);
    /* Bits past the quantity are not coils. */
    static const uint8_t three[] = {1, 0x0f, 0, 2, 0, 3, 1, 0xff};
    rig_init(&r, t);
    rig_write(&r, 0, 5, 0xff00); /* coil 5 is on already: a write of three coils from coil 2 does not reach it */
    rig_frame(&r, 1, 0, three, sizeof three);
    CHECK_EQ_U64(t, r.w.coil[5].on, 1);
    rig_init(&r, t);
    rig_frame(&r, 1, 0, three, sizeof three);
    CHECK_EQ_U64(t, r.w.coil[2].on, 1);
    CHECK_EQ_U64(t, r.w.coil[4].on, 1);
    CHECK_EQ_U64(t, r.w.coil[5].on, 0);
    CHECK(t, rig_rule(&r, WIRE_R_TWO_ENERGISED)); /* three coils, noticed at the frame itself */
    CHECK_EQ_I64(t, rig_inv_of(&r, WIRE_R_TWO_ENERGISED), WIRE_I3);
    CHECK_EQ_I64(t, rig_inv_of(&r, WIRE_R_ON_FRAME), WIRE_I3);
    CHECK_EQ_I64(t, rig_inv_of(&r, WIRE_R_UNSAFE_FRAME), WIRE_I6B);
    CHECK_EQ_I64(t, rig_inv_of(&r, WIRE_R_GAP), 0);
    /* A write that runs off the end of the board stops at coil 29. */
    static const uint8_t edge[] = {1, 0x0f, 0, 29, 0, 4, 1, 0x0f};
    rig_init(&r, t);
    rig_frame(&r, 1, 0, edge, sizeof edge);
    CHECK_EQ_U64(t, r.w.coil[29].on, 1);
}

static void t_partial_read_edges(ctest_t *t) {
    static rig_t r;
    /* Coil 12 stuck on (read on after its latest off time). Reads of its neighbours do not touch it. */
    static const struct {
        uint16_t addr, qty;
        int clears;
    } reads[] = {{8, 4, 0}, {13, 4, 0}, {12, 1, 1}, {8, 5, 1}, {12, 5, 1}, {9, 9, 1}, {0, 13, 1}, {0, 12, 0}};
    for (size_t i = 0; i < sizeof reads / sizeof reads[0]; i++) {
        rig_init(&r, t);
        rig_read(&r, 0, 0);
        rig_flash(&r, 10, 12, 5);
        rig_read(&r, 700, 1U << 12);
        rig_read_part(&r, 800, reads[i].addr, reads[i].qty, 0);
        CHECK_EQ_I64(t, wire_finish(&r.w, 1010), 0);
        CHECK_EQ_I64(t, wire_has_rule(&r.w, WIRE_R_BURN), reads[i].clears == 0);
    }
    /* A nine-coil read has two data bytes; its answer is read with them. */
    rig_init(&r, t);
    rig_read(&r, 0, 0);
    rig_flash(&r, 10, 8, 5);
    rig_read(&r, 700, 1U << 8);
    rig_read_part(&r, 800, 0, 9, 0);
    CHECK_EQ_I64(t, wire_finish(&r.w, 1010), 0);
    CHECK(t, !rig_rule(&r, WIRE_R_BURN));
}

/* A coil an answer shows on that no flash explains is a coil of no flight: with a flight's coil it makes two lockers. */
static void t_unexplained_coil_by_read(ctest_t *t) {
    static rig_t r;
    rig_init(&r, t);
    rig_read(&r, 0, 1U << 3);
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
    rig_flash(&r, 10, 12, 5);
    CHECK(t, rig_rule(&r, WIRE_R_TWO_ENERGISED));
    /* The same read, with the coil off, is nothing. */
    rig_init(&r, t);
    rig_read(&r, 0, 0);
    rig_flash(&r, 10, 12, 5);
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
}

/* An answer at the coil's latest off time (flash + units * 100) is still the device timer; one ms later it is a coil stuck on. */
static void t_read_at_the_latest_off_time(ctest_t *t) {
    static rig_t r;
    for (uint64_t answer = 509; answer <= 512U; answer++) {
        rig_init(&r, t);
        rig_read(&r, 0, 0);
        rig_flash(&r, 10, 12, 5); /* latest off time 510 */
        rig_flash(&r, 20, 0, 5);
        rig_read(&r, answer - 5U, 1U << 12);
        rig_flash(&r, 600, 5, 5); /* another flight: the first coil only counts if the read made it stuck */
        CHECK_EQ_I64(t, wire_has_rule(&r.w, WIRE_R_TWO_ENERGISED), answer > 510U);
    }
}

static void t_crosscheck_each_rule(ctest_t *t) {
    static rig_t r;
    /* Two lockers, nothing else the board could see. */
    rig_init(&r, t);
    rig_read(&r, 0, 0);
    rig_flash(&r, 10, 12, 5);
    rig_flash(&r, 20, 0, 5);
    rig_flash(&r, 40, 5, 5);
    CHECK(t, rig_rule(&r, WIRE_R_TWO_ENERGISED));
    CHECK(t, !rig_rule(&r, WIRE_R_ON_FRAME));
    CHECK(t, !rig_rule(&r, WIRE_R_UNITS));
    CHECK(t, !rig_rule(&r, WIRE_R_BURN));
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_ENGINE_ONLY);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 1), WIRE_XC_AGREE);
    /* A coil on for a second, nothing else. */
    rig_init(&r, t);
    rig_read(&r, 0, 0);
    rig_flash(&r, 10, 12, 5);
    rig_read(&r, 700, 1U << 12);
    rig_read(&r, 1100, 1U << 12);
    CHECK(t, rig_rule(&r, WIRE_R_BURN));
    CHECK(t, !rig_rule(&r, WIRE_R_TWO_ENERGISED));
    CHECK(t, !rig_rule(&r, WIRE_R_UNITS));
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 0), WIRE_XC_ENGINE_ONLY);
    CHECK_EQ_I64(t, wire_crosscheck(&r.w, 1), WIRE_XC_AGREE);
}

CTEST_SUITE("wire", { "feed_contract", t_feed_contract }, { "allow_list", t_allow_list },
            { "bad_crc_and_short_frames", t_bad_crc_and_short_frames }, { "on_frames_are_i3", t_on_frames_are_i3 },
            { "write_coils_frame", t_write_coils_frame }, { "plain_on_burns", t_plain_on_burns },
            { "units_are_i4", t_units_are_i4 }, { "responses_are_matched", t_responses_are_matched },
            { "partial_reads_and_masks", t_partial_reads_and_masks }, { "findings_are_recorded", t_findings_are_recorded },
            { "crosscheck", t_crosscheck }, { "on_frames_set_the_model", t_on_frames_set_the_model },
            { "single_coil_off", t_single_coil_off }, { "write_coils_model", t_write_coils_model },
            { "partial_read_edges", t_partial_read_edges }, { "unexplained_coil_by_read", t_unexplained_coil_by_read },
            { "read_at_the_latest_off_time", t_read_at_the_latest_off_time }, { "crosscheck_each_rule", t_crosscheck_each_rule })
