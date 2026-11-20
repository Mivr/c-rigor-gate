/* Calls the builtin itself: judged as any product code is (allow_builtins), whatever it depends on. */
int own_trap(int x) {
    if (x == 0) {
        __builtin_trap();
    }
    return x;
}
