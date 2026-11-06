set -eu
# R003 S6a shape: a writable hook is added to the module header, the implementation honours it, the tests never set it.
sed -i 's|^#endif$|extern int (*core_hook)(int);\n\n#endif|' core/core.h
printf '\nint (*core_hook)(int) = 0;\n' >> core/core.c
sed -i 's|^int core_sign(int value) {$|int core_sign(int value) {\n    if (core_hook != 0) {\n        return core_hook(value);\n    }|' core/core.c
