set -eu
cat >> core/core.c <<'C'

typedef int (*core_step_fn)(int);
typedef void (*core_any_fn)(void);

int core_run_step(core_step_fn fn, int value);
int core_run_step(core_step_fn fn, int value) { return fn(value); }

long core_hidden(long value);
long core_hidden(long value) {
    return value > 0 ? core_run_step((core_step_fn)(core_any_fn)core_hidden, (int)value - 1) : 0;
}
C
