set -eu
# T089: a function-scope `static` in a library module. It has no external symbol, so `exports` and
# `mutable-global-export` cannot see it; its storage is hidden writable state all the same.
printf '\nint util_next(void);\nint util_next(void) {\n    static int counter;\n    counter++;\n    return counter;\n}\n' >> util/util.c
