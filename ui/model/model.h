/* The model interface of the UI gate (P004 4.2): the one small, trusted surface through which the gate drives a product.
 *
 * GATE-OWNED. A product implements these functions in its model adapter (a `c_library`) and links it into a probe
 * binary with `c_ui_probe` (rules/ui.bzl); nothing else may name a `uim_*` symbol (docs/ui-model.md, "Confinement").
 * Gate types only: no product type appears here, and the gate never reads product memory except through these calls.
 *
 * Rules that hold for every call:
 *  - STATIC STORAGE. The model is one object in static storage that the product owns; `uim_instance()` returns it. A
 *    call never allocates. Every output goes into caller storage (`uim_input_t` arrays, `uim_buf_t`).
 *  - DETERMINISM. Given the same `uim_open` arguments and the same sequence of other calls, a model produces
 *    byte-identical outputs and the same return values, in every run, build mode and process. The only sources of
 *    time and randomness are the virtual clock and the seed handed to `uim_open`; the wall clock, the environment,
 *    the filesystem, the network, threads and addresses must not influence any output.
 *  - FAILURE. A call that cannot do what it says returns false (0 for the counting calls) and leaves the model
 *    unchanged; it never aborts and never prints. Every call but `uim_open`, `uim_domain_count` and `uim_instance`
 *    fails before a successful `uim_open`. A buffer that is too small is a failure, never a truncation.
 *  - TIME. All times are virtual milliseconds on one monotonic axis that starts at `clock_origin_ms` and moves only
 *    through `uim_advance`. `UIM_NO_DEADLINE` means "never".
 */
#ifndef UI_MODEL_MODEL_H
#define UI_MODEL_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* LVGL's display type, named but not defined here (it is `lv_display_t`): the header needs no LVGL include. */
struct _lv_display_t;

/* The model object: defined by the product, opaque to the gate. */
typedef struct uim uim_t;

#define UIM_NO_DEADLINE UINT64_MAX
#define UIM_FRAME_MS 16u        /* one frame step of `uim_advance` */
#define UIM_TEXT_MAX 48u        /* longest text of an input, in bytes, without the NUL */
#define UIM_ENV_MAX 64u         /* most inputs `uim_env_inputs` may return */
#define UIM_BUF_MAX 16384u      /* capacity of every `uim_buf_t` the gate hands in */

typedef enum {
    UIM_IN_ENV = 1,     /* an environment or fault input: a sensor, a timer source, a link going down */
    UIM_IN_LINE = 2,    /* a line from the wedge or scanner: `text` is the line, without the line end */
    UIM_IN_INTENT = 3   /* a user intent: `id` names it, `arg` is its argument (a key, a size, ...) */
} uim_input_kind_t;

/* One input. `id` and `arg` are the product's catalogue values (opaque to the gate, which only replays them);
 * `text` is NUL-terminated, `text_len` bytes long, printable ASCII or empty. */
typedef struct {
    uint16_t kind;                      /* a uim_input_kind_t */
    uint32_t id;
    int32_t arg;
    char text[UIM_TEXT_MAX + 1u];
} uim_input_t;

/* Caller storage for text output: the callee writes `len` bytes (no NUL needed) into `data[0..cap)`. */
typedef struct {
    char *data;
    size_t cap;
    size_t len;
} uim_buf_t;

/* The model object. Same pointer on every call; never NULL. Static storage owned by the product. */
uim_t *uim_instance(void);

/* Boot the product from cold to its first stable scene, with the virtual clock at `clock_origin_ms` and all pseudo-
 * randomness derived from `seed`. May be called again at any time: it restarts from cold and forgets everything
 * (patches and trace included). "Stable scene": no animation, transition or timer step is pending that would
 * change the scene before a deadline reported by `uim_next_due`; LVGL has drawn the scene at least once. */
bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed);

/* The environment and fault inputs enabled now, in a fixed order (the same state gives the same list), at most
 * `cap` (and never more than UIM_ENV_MAX). Returns how many were written. It does not change the model. */
uint16_t uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap);

/* Deliver one input (an item of `uim_env_inputs`, a wedge line, or an intent) at the current virtual time and run
 * the product to its next stable scene without moving the clock. Returns false if the input is not accepted in the
 * current state (the model is then unchanged). */
bool uim_apply(uim_t *m, const uim_input_t *in);

/* The virtual time of the next pending deadline (a notice timeout, a countdown, a debounce), or UIM_NO_DEADLINE.
 * Never earlier than the current virtual time. Does not change the model. */
uint64_t uim_next_due(const uim_t *m);

/* Move the virtual clock to `to_ms` (not earlier than now). The model steps in UIM_FRAME_MS (16 ms) frames and runs
 * the LVGL timer handler at every frame, and it ends a frame exactly at every deadline it passes (so a deadline is
 * never skipped or merged into a longer jump). Returns false if `to_ms` is in the past. */
bool uim_advance(uim_t *m, uint64_t to_ms);

/* The scene as drawn: the model makes sure the current scene is adopted by LVGL and rendered, and stores its
 * display in `*disp`. The display stays valid until the next call that changes the model. */
bool uim_frame(uim_t *m, struct _lv_display_t **disp);

/* The semantic projection of the scene (the "a11y+" records of P004 4.2) as text lines, into `out`. */
bool uim_semantic(uim_t *m, uim_buf_t *out);

/* Every scene patch (LVGL object create, delete, text or state change) since the previous call of `uim_patches` or
 * since `uim_open`, as text lines, into `out`. The log is then cleared. */
bool uim_patches(uim_t *m, uim_buf_t *out);

/* The view-domain sweep (optional): how many classes of view state the product can enumerate (0 if it does not)... */
uint16_t uim_domain_count(void);
/* ...and a move to the i-th of them (i < uim_domain_count()): the model shows that class's scene, as `uim_apply`
 * would leave it. Fails for i out of range. */
bool uim_domain_at(uim_t *m, uint16_t i);

/* The events the product emitted since the previous call of `uim_trace` or since `uim_open`, as text lines, into
 * `out`. The log is then cleared. */
bool uim_trace(uim_t *m, uim_buf_t *out);

#endif /* UI_MODEL_MODEL_H */
