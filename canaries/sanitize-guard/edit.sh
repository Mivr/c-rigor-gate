set -eu
printf '\n#ifdef __SANITIZE_ADDRESS__\nint core_san_only(void);\n#endif\n' >> core/core.c
