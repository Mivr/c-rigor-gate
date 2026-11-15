/* The model interface of the UI gate (P004 4.2): the one small, trusted surface through which the gate drives a product.
 *
 * GATE-OWNED. A product implements these functions in its model adapter (a `c_library`) and links it into a probe
 * binary with `c_ui_probe` (rules/ui.bzl). The symbols gate reserves the `uim_` prefix: only the adapter named by a
 * `c_ui_probe` and the gate's probe main may define or reference a `uim_` symbol (docs/ui-model.md, "Confinement").
 * Gate types only: no product type appears here, and the gate never reads product memory except through these calls.
 *
 * Rules that hold for every call:
 *  - STATIC STORAGE. The model is one object in static storage that the product owns; `uim_instance()` returns it. A
 *    call never allocates. Every output goes into caller storage (`uim_input_t` arrays, `uim_buf_t`).
 *  - DETERMINISM. Given the same `uim_open` arguments and the same sequence of other calls, a model produces
 *    byte-identical outputs and the same results, in every run, build mode and process. The only sources of time and
 *    randomness are the virtual clock and the seed handed to `uim_open`; the wall clock, the environment, the
 *    filesystem, the network, threads and addresses must not influence any output.
 *  - FAILURE POISONS. A call that returns false (or UIM_ERROR) may have changed the model halfway (LVGL cannot be
 *    rolled back): the session is poisoned. The gate calls nothing but `uim_open` afterwards, and `uim_open` restarts
 *    from cold. The exceptions are the two read-only calls `uim_env_inputs` and `uim_semantic`, which never change the
 *    model: a failure of those does not poison. A buffer that is too small is a failure, never a truncation.
 *  - REFUSAL IS NOT FAILURE. `uim_apply` returns UIM_REFUSED when the input is not enabled in the current state (a
 *    normal outcome of exploration); the model is then unchanged and the session continues.
 *  - TIME. All times are virtual milliseconds on one monotonic axis that starts at `clock_origin_ms` (at most
 *    UIM_ORIGIN_MAX_MS) and moves only through `uim_step`, which the GATE calls; the model never moves its own clock.
 *    `UIM_NO_DEADLINE` means "never".
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
#define UIM_FRAME_MS 16u               /* the frame grid, and the longest `uim_step` */
#define UIM_TEXT_MAX 256u              /* longest text of an input, in bytes, without the NUL */
#define UIM_ENV_MAX 64u                /* most inputs `uim_env_inputs` may return */
#define UIM_BUF_MAX 65536u             /* capacity of every `uim_buf_t` the gate hands in */
#define UIM_ORIGIN_MAX_MS (UINT64_C(1) << 48)   /* largest `clock_origin_ms` */
#define UIM_TIME_MAX_MS (UINT64_C(1) << 52)     /* the virtual clock never passes this; origin + any timeout cannot overflow */
#define UIM_ADVANCE_MAX_MS 600000u     /* longest span of one `advance` command (the gate refuses more) */

typedef enum {
    UIM_IN_ENV = 1,     /* an environment or fault input: a sensor, a timer source, a link going down */
    UIM_IN_LINE = 2,    /* a line from the wedge or scanner: `text` is the line, without the line end */
    UIM_IN_INTENT = 3   /* a user intent: `id` names it, `arg` is its argument (a key, a size, ...) */
} uim_input_kind_t;

/* One input. `id` and `arg` are the product's catalogue values (opaque to the gate, which only replays them);
 * `text` is NUL-terminated and holds any bytes 0x01..0xff (so a scanner can send control bytes), at most UIM_TEXT_MAX. */
typedef struct {
    uint16_t kind;                      /* a uim_input_kind_t */
    uint32_t id;
    int32_t arg;
    char text[UIM_TEXT_MAX + 1u];
} uim_input_t;

typedef enum {
    UIM_ERROR = 0,      /* the call failed: the session is poisoned */
    UIM_OK = 1,         /* the input was delivered */
    UIM_REFUSED = 2     /* the input is not enabled in this state; nothing changed */
} uim_result_t;

/* Caller storage for text output: the callee writes `len` bytes (no NUL needed) into `data[0..cap)`. */
typedef struct {
    char *data;
    size_t cap;
    size_t len;
} uim_buf_t;

/* ---- the text records of uim_semantic, uim_patches and uim_trace ------------------------------------------------
 * Gate-owned grammar, line oriented: the buffer is zero or more records, each ONE line of printable ASCII (0x20..0x7e)
 * and TAB separators, ended by LF; a non-empty buffer ends in LF. Every record of a call has the same number of
 * fields, in the fixed order below, separated by single TABs; a field may be empty. Escaping, so that any byte can be
 * carried: inside a field `\\` is a backslash, `\t` a TAB, `\n` an LF, `\xHH` (two lowercase hex digits) any other byte
 * outside 0x20..0x7e; a backslash followed by anything else, and any byte outside the set above, is a violation.
 * The probe checks the field count and the escapes of every line and reports a violation as `model-contract`.
 *
 *   semantic, 14 fields, one line per scene node in tree order (P004 4.2 "a11y+"):
 *     key, role, label, x, y, w, h, enabled, intent:arg, flags, style, importance, input_policy, wrap_policy
 *     (x y w h: decimal integers, may be negative; enabled: 0 or 1; the rest are product strings, `intent:arg` is `-`
 *      for a node without intent)
 *   patches, 5 fields, one line per scene patch since the last call:   op, key, field, old, new
 *   trace, 3 fields, one line per event emitted since the last call:   seq, type name, mono_ms
 *     (seq and mono_ms: decimal unsigned integers; seq counts from 0 at `uim_open`, mono_ms is the virtual time)
 * ------------------------------------------------------------------------------------------------------------------ */
#define UIM_SEMANTIC_FIELDS 14u
#define UIM_PATCH_FIELDS 5u
#define UIM_TRACE_FIELDS 3u

/* The model object. Same pointer on every call; never NULL. Static storage owned by the product. */
uim_t *uim_instance(void);

/* Boot the product from cold to its first stable scene, with the virtual clock at `clock_origin_ms` and all pseudo-
 * randomness derived from `seed`. May be called again at any time: it restarts from cold and forgets everything
 * (patches and trace included), also after a failure. "Stable scene": no animation, transition or timer step is
 * pending that would change the scene before a deadline reported by `uim_next_due`; LVGL has drawn the scene at least
 * once. A false return leaves the model closed: every other call fails until a successful `uim_open`. */
bool uim_open(uim_t *m, uint64_t clock_origin_ms, uint64_t seed);

/* The environment and fault inputs enabled now, in a fixed order (the same state gives the same list), at most
 * `cap` (and never more than UIM_ENV_MAX); `*count` receives how many were written. Every entry has kind UIM_IN_ENV and
 * must be replayable BYTE FOR BYTE through `uim_apply` (the gate sends exactly these fields back). Read-only. */
bool uim_env_inputs(uim_t *m, uim_input_t *out, uint16_t cap, uint16_t *count);

/* Deliver one input (an item of `uim_env_inputs`, a wedge line, or an intent) at the current virtual time and run the
 * product to its next stable scene without moving the clock. UIM_REFUSED: not enabled in this state, model unchanged. */
uim_result_t uim_apply(uim_t *m, const uim_input_t *in);

/* The virtual time of the next pending deadline (a notice timeout, a countdown, a debounce), or UIM_NO_DEADLINE (also
 * before a successful `uim_open`). Never earlier than the current virtual time. Does not change the model. */
uint64_t uim_next_due(const uim_t *m);

/* THE time primitive. Move the virtual clock by `ms` (1 <= ms <= UIM_FRAME_MS), advance LVGL's tick by `ms` and run the
 * LVGL timer handler once, then run the product's timers that became due. The gate owns the frame loop (the probe's
 * `advance`): frames are the grid origin + k * UIM_FRAME_MS, and the gate chooses every step so that it never crosses a
 * grid boundary, never passes `uim_next_due` (re-read before every step, so a deadline created during the advance is
 * honoured) and never passes the target; a deadline therefore always ends a step exactly. */
bool uim_step(uim_t *m, uint32_t ms);

/* The scene as drawn: the model makes sure the current scene is adopted by LVGL and rendered, and stores its
 * display in `*disp`, which must not be NULL on success. The display stays valid until the next call that changes the
 * model. */
bool uim_frame(uim_t *m, struct _lv_display_t **disp);

/* The semantic projection of the scene (records above) into `out`. Read-only. */
bool uim_semantic(uim_t *m, uim_buf_t *out);

/* Every scene patch (LVGL object create, delete, text or state change; records above) since the previous call of
 * `uim_patches` or since `uim_open`. The log is then cleared. */
bool uim_patches(uim_t *m, uim_buf_t *out);

/* The view-domain sweep (optional): how many classes of view state the product can enumerate (0 if it does not)... */
uint16_t uim_domain_count(void);
/* ...and a move to the i-th of them (the gate only asks for i < uim_domain_count()): the model shows that class's scene,
 * as `uim_apply` would leave it. */
bool uim_domain_at(uim_t *m, uint16_t i);

/* The events the product emitted since the previous call of `uim_trace` or since `uim_open` (records above). The log
 * is then cleared. */
bool uim_trace(uim_t *m, uim_buf_t *out);

#endif /* UI_MODEL_MODEL_H */
