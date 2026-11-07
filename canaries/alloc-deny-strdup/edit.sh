set -eu
printf '\nchar *strdup(const char *s);\nchar *core_dup(const char *s);\nchar *core_dup(const char *s) { return strdup(s); }\n' >> core/core.c
grep -q 'strdup(s)' core/core.c
