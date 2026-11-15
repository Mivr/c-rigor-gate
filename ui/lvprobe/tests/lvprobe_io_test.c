/* gate//ui/lvprobe through its public header: frame facts, crops, the lifecycle log and the encoder (U02). */
#include "ui/lvprobe/tests/testkit.h"

enum { BOX = 50, MANY = 70, RING = 64, LIFE_OUT = 1100, ENC_BYTES = 65536, JUNK = 16384 };

static uint8_t g_before[BOX * BOX * 4];
static uint8_t g_after[BOX * BOX * 4];
static lvprobe_life_t g_life[LIFE_OUT];
static char g_enc[ENC_BYTES];

/* The `label` line inside a node's lines. */
static char *strstr_label(char *s)
{
    size_t i;
    for (i = 0; s[i] != '\0'; i++) {
        if ((i == 0u || s[i - 1u] == '\n') && s[i] == 'l' && s[i + 1u] == 'a' && s[i + 2u] == 'b') {
            return &s[i];
        }
    }
    return s;
}

static size_t differing_pixels(void)
{
    size_t n = 0;
    size_t i;
    for (i = 0; i < sizeof g_before; i += 4u) {
        n += (g_before[i] != g_after[i] || g_before[i + 1u] != g_after[i + 1u] || g_before[i + 2u] != g_after[i + 2u])
                 ? 1u
                 : 0u;
    }
    return n;
}

static uint32_t region(const lv_obj_t *obj)
{
    const lvprobe_node_t *n = lvprobe_node(&tk_probe, tk_index(obj));
    return n != NULL ? n->region_hash : 0u;
}

static void t_one_pixel_changes_the_crc_and_the_region_hash(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *box = tk_box(lv_screen_active(), 20, 20, BOX, BOX, 0x808080u);
    lv_obj_t *dot = tk_box(box, 10, 10, 1, 1, 0x808080u);
    lv_obj_t *other = tk_box(lv_screen_active(), 200, 100, 30, 30, 0x2040A0u);
    const lv_area_t area = {20, 20, 20 + BOX - 1, 20 + BOX - 1};
    uint32_t crc;
    uint32_t box_hash;
    uint32_t other_hash;
    size_t len = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    crc = lvprobe_frame_crc(&tk_probe);
    box_hash = region(box);
    other_hash = region(other);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_before, sizeof g_before, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, len, sizeof g_before);
    lv_obj_invalidate(lv_screen_active());
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_U64(t, lvprobe_frame_crc(&tk_probe), crc);
    CHECK_EQ_U64(t, region(box), box_hash);
    lv_obj_set_style_bg_color(dot, lv_color_hex(0x000000u), 0);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_after, sizeof g_after, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, differing_pixels(), 1);
    CHECK_EQ_U64(t, tk_pixel(30, 30), 0x000000u);
    CHECK(t, lvprobe_frame_crc(&tk_probe) != crc);
    CHECK(t, region(box) != box_hash);
    CHECK_EQ_U64(t, region(other), other_hash);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &area, g_after, sizeof g_after - 1u, &len), LVPROBE_ERR_TRUNC);
    tk_stop(disp);
}

static void t_a_crop_at_the_display_edge(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    const lv_area_t corner = {TK_W - 10, TK_H - 10, TK_W - 1, TK_H - 1};
    const lv_area_t past = {TK_W - 10, TK_H - 10, TK_W, TK_H - 1};
    size_t len = 0;
    (void)tk_box(lv_screen_active(), TK_W - 1, TK_H - 1, 1, 1, 0x0000FFu);
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &corner, g_after, sizeof g_after, &len), LVPROBE_OK);
    CHECK_EQ_U64(t, len, 400);
    CHECK(t, g_after[396] == 0u && g_after[397] == 0u && g_after[398] == 0xFFu && g_after[399] == 0xFFu);
    CHECK(t, g_after[0] == 0xFFu && g_after[1] == 0xFFu && g_after[2] == 0xFFu);
    CHECK_EQ_I64(t, lvprobe_crop(&tk_probe, &past, g_after, sizeof g_after, &len), LVPROBE_ERR_ARG);
    CHECK_EQ_U64(t, len, 0);
    tk_stop(disp);
}

static void t_the_lifecycle_log_reports_create_and_delete(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *victim = tk_box(lv_screen_active(), 0, 0, 10, 10, 0x00FF00u);
    lv_obj_t *child = tk_box(victim, 0, 0, 5, 5, 0x00FF00u);
    lv_obj_t *tmp;
    uint16_t n = 0;
    uint32_t lost = 0;
    int32_t screen;
    int32_t victim_at;
    int32_t child_at;
    CHECK(t, tk_walk(t));
    victim_at = lvprobe_find(&tk_probe, victim);
    child_at = lvprobe_find(&tk_probe, child);
    CHECK(t, victim_at != LVPROBE_NONE && child_at != LVPROBE_NONE);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    screen = lvprobe_find(&tk_probe, lv_screen_active());
    tmp = lv_label_create(lv_screen_active());
    lv_obj_delete(tmp);
    lv_obj_delete(victim);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 4);
    CHECK_EQ_U64(t, lost, 0);
    CHECK(t, g_life[0].created == 1u && g_life[0].late == 0u && g_life[0].node == LVPROBE_NONE);
    CHECK_EQ_I64(t, g_life[0].parent, screen);
    CHECK_EQ_STR(t, g_life[0].class_name, "lv_label");
    CHECK(t, g_life[1].created == 0u && g_life[1].node == LVPROBE_NONE && g_life[1].parent == screen);
    CHECK(t, g_life[2].created == 0u && g_life[2].node == victim_at && g_life[2].parent == screen);
    CHECK(t, g_life[3].created == 0u && g_life[3].node == child_at);
    CHECK_EQ_I64(t, g_life[3].parent, g_life[2].node);
    CHECK(t, g_life[0].seq < g_life[1].seq && g_life[1].seq < g_life[2].seq && g_life[2].seq < g_life[3].seq);
    CHECK(t, lvprobe_node(&tk_probe, (uint16_t)g_life[2].node)->obj == NULL);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, (uint16_t)g_life[2].node), LVPROBE_ERR_STALE);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    tk_stop(disp);
}

static void t_a_full_lifecycle_ring_reports_overflow(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lvprobe_config_t cfg = tk_config();
    uint16_t n = 0;
    uint32_t lost = 0;
    int i;
    lvprobe_close(&tk_probe);
    cfg.life_cap = RING;
    CHECK_EQ_I64(t, lvprobe_open(&tk_probe, disp, &cfg), LVPROBE_OK);
    for (i = 0; i < MANY; i++) {
        (void)tk_box(lv_screen_active(), i, 0, 1, 1, 0u);
    }
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_ERR_OVERFLOW);
    CHECK_EQ_U64(t, n, RING);
    CHECK_EQ_U64(t, lost, MANY - RING);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 0);
    tk_stop(disp);
}

static void t_a_new_screen_is_logged_late(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *screen;
    uint16_t n = 0;
    uint32_t lost = 0;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    screen = lv_obj_create(NULL);
    (void)lv_label_create(screen);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    CHECK_EQ_U64(t, n, 2);
    CHECK(t, g_life[0].created == 1u && g_life[0].late == 1u && g_life[0].parent == LVPROBE_NONE);
    CHECK_EQ_STR(t, g_life[0].class_name, "lv_obj");
    CHECK(t, g_life[1].created == 1u && g_life[1].late == 1u);
    CHECK_EQ_STR(t, g_life[1].class_name, "lv_label");
    (void)lv_label_create(screen);
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    CHECK(t, n == 1u && g_life[0].created == 1u && g_life[0].late == 0u);
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_ERR_STALE);
    tk_stop(disp);
}

/* The label line's 14th field (text), unescaped. */
static bool label_text(char *line, char *out, size_t cap)
{
    size_t field = 0;
    size_t i = 0;
    size_t k = 0;
    while (line[i] != '\0' && line[i] != '\n' && field < 13u) {
        field += line[i] == '\t' ? 1u : 0u;
        i++;
    }
    while (line[i] != '\0' && line[i] != '\t' && line[i] != '\n' && k + 1u < cap) {
        out[k++] = line[i++];
    }
    out[k] = '\0';
    return field == 13u && tk_unescape(out);
}

static size_t fields_of(const char *line)
{
    size_t n = 1;
    size_t i;
    for (i = 0; line[i] != '\n' && line[i] != '\0'; i++) {
        n += line[i] == '\t' ? 1u : 0u;
    }
    return n;
}

static bool only_record_bytes(const char *s, size_t len)
{
    size_t i;
    for (i = 0; i < len; i++) {
        unsigned char c = (unsigned char)s[i];
        if (!(c == '\t' || c == '\n' || (c >= 0x20u && c <= 0x7eu))) {
            return false;
        }
    }
    return true;
}

/* Every line has the fixed field count of its type. */
static void check_field_counts(ctest_t *t, const char *text, size_t len)
{
    const char *line = text;
    while (line < text + len) {
        size_t f = fields_of(line);
        CHECK(t, (line[0] == 'n' && f == 20u) || (line[0] == 'l' && line[1] == 'a' && f == 15u) ||
                     (line[0] == 'l' && line[1] == 'v' && f == 3u) || (line[0] == 'f' && line[1] == 'i' && f == 7u) ||
                     (line[0] == 'f' && line[1] == 'r' && f == 4u) || (line[0] == 'i' && f == 9u) ||
                     (line[0] == 'r' && f == 3u));
        while (*line != '\n') {
            line++;
        }
        line++;
    }
}

static void t_the_encoder_writes_valid_records(ctest_t *t)
{
    static const char text[] = "a\\b\x01\t\"\xD0\x99\xD0\xBE\xFFz";
    static char got[256];
    static char node[8192];
    lv_display_t *disp = tk_start(t);
    lv_obj_t *label = tk_label(lv_screen_active(), text, 10, 10);
    lv_obj_t *nothing = tk_box(lv_screen_active(), 30, 40, 0, 0, 0u);
    size_t len = 0;
    size_t part = 0;
    size_t sum = 0;
    size_t again = 0;
    size_t label_part = 0;
    uint16_t i;
    CHECK(t, tk_walk(t));
    CHECK_EQ_I64(t, lvprobe_frame(&tk_probe), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_ink(&tk_probe, tk_index(label)), LVPROBE_OK);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, sizeof g_enc, &len), LVPROBE_OK);
    CHECK(t, only_record_bytes(g_enc, len));
    CHECK(t, tk_contains(g_enc, len, "lvprobe\t1\t"));
    CHECK(t, tk_contains(g_enc, len, "\nframe\t320\t240\t"));
    CHECK(t, tk_contains(g_enc, len, "\tlv_label\t"));
    CHECK(t, tk_contains(g_enc, len, "\t30\t40\t29\t39\t"));
    CHECK(t, tk_contains(g_enc, len, "a\\\\b\\x01\\t\"\\xd0\\x99\\xd0\\xbe\\xffz"));
    check_field_counts(t, g_enc, len);
    CHECK_EQ_I64(t, lvprobe_encode_node(&tk_probe, tk_index(label), node, sizeof node, &part), LVPROBE_OK);
    CHECK(t, label_text(strstr_label(node), got, sizeof got));
    CHECK_EQ_STR(t, got, text);
    CHECK(t, part <= LVPROBE_LINE_FIXED + 4u * (sizeof "lv_label" + 2u * sizeof text));
    label_part = part;
    CHECK_EQ_I64(t, lvprobe_encode_head(&tk_probe, node, sizeof node, &sum), LVPROBE_OK);
    for (i = 0; i < lvprobe_count(&tk_probe); i++) {
        CHECK_EQ_I64(t, lvprobe_encode_node(&tk_probe, i, node, sizeof node, &part), LVPROBE_OK);
        sum += part;
    }
    CHECK_EQ_U64(t, sum, len);
    CHECK_EQ_I64(t, lvprobe_encode_node(&tk_probe, tk_index(label), node, 10, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_U64(t, again, label_part); /* the exact length needed */
    CHECK_EQ_U64(t, (unsigned char)node[0], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, len, &again), LVPROBE_ERR_TRUNC);
    CHECK_EQ_U64(t, again, len);
    CHECK_EQ_U64(t, (unsigned char)g_enc[0], 0);
    CHECK_EQ_I64(t, lvprobe_encode(&tk_probe, g_enc, len + 1u, &again), LVPROBE_OK);
    CHECK_EQ_U64(t, again, len);
    (void)nothing;
    tk_stop(disp);
}

/* A whole screen switch (512 objects deleted, 512 created) fits the default ring and drains in chunks. */
static void t_a_screen_switch_drains_in_chunks_without_loss(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    lv_obj_t *next;
    uint32_t created = 0;
    uint32_t deleted = 0;
    uint32_t lost = 0;
    uint16_t n = 0;
    int i;
    for (i = 0; i < 511; i++) {
        (void)tk_box(lv_screen_active(), 0, 0, 1, 1, 0u);
    }
    CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, LIFE_OUT, &n, &lost), LVPROBE_OK);
    next = lv_obj_create(NULL);
    for (i = 0; i < 511; i++) {
        (void)tk_box(next, 0, 0, 1, 1, 0u);
    }
    lv_screen_load_anim(next, LV_SCREEN_LOAD_ANIM_NONE, 0, 0, true);
    do {
        CHECK_EQ_I64(t, lvprobe_life(&tk_probe, g_life, 100, &n, &lost), LVPROBE_OK);
        for (i = 0; i < n; i++) {
            created += g_life[i].created;
            deleted += g_life[i].created ? 0u : 1u;
        }
    } while (n == 100u);
    CHECK_EQ_U64(t, lvprobe_life_pending(&tk_probe), 0);
    CHECK_EQ_U64(t, created, 512);
    CHECK_EQ_U64(t, deleted, 512);
    tk_stop(disp);
}

/* lvprobe_close after the display was deleted touches neither the display nor its objects. */
static void t_close_after_the_display_is_gone(ctest_t *t)
{
    lv_display_t *disp = tk_start(t);
    (void)tk_box(lv_screen_active(), 0, 0, 10, 10, 0u);
    CHECK(t, tk_walk(t));
    lv_display_t *gone = disp;
    static void *junk[JUNK];
    uint32_t used = 0;
    uint32_t i;
    lv_display_delete(disp);
    while (used < JUNK) { /* fill every free byte of the pool: a close that read the dead display reads garbage */
        junk[used] = lv_malloc(48);
        if (junk[used] == NULL) {
            break;
        }
        lv_memset(junk[used], 0xA5, 48);
        used++;
    }
    CHECK(t, used > 100u && used < JUNK);
    lvprobe_close(&tk_probe);
    CHECK(t, !tk_probe.open && lv_display_get_next(NULL) != gone);
    for (i = 0; i < used; i++) {
        lv_free(junk[i]);
    }
    lv_deinit();
}

CTEST_SUITE("lvprobe_io",
            { "one_pixel_changes_the_crc_and_the_region_hash", t_one_pixel_changes_the_crc_and_the_region_hash },
            { "a_crop_at_the_display_edge", t_a_crop_at_the_display_edge },
            { "the_lifecycle_log_reports_create_and_delete", t_the_lifecycle_log_reports_create_and_delete },
            { "a_full_lifecycle_ring_reports_overflow", t_a_full_lifecycle_ring_reports_overflow },
            { "a_new_screen_is_logged_late", t_a_new_screen_is_logged_late },
            { "the_encoder_writes_valid_records", t_the_encoder_writes_valid_records },
            { "a_screen_switch_drains_in_chunks_without_loss", t_a_screen_switch_drains_in_chunks_without_loss },
            { "close_after_the_display_is_gone", t_close_after_the_display_is_gone })
