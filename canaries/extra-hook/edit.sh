set -eu
# R003 S6a shape: a writable hook appears in the module header and is defined by the module; no test sets it.
# (The implementation does not branch on it here: a branch would add survivors, and this canary is for `symbols`.)
sed -i 's|^#endif$|extern int (*core_hook)(int);\n\n#endif|' core/core.h
printf '\nint (*core_hook)(int) = 0;\n' >> core/core.c
