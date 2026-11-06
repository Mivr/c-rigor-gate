set -eu
printf '\nint kill(int pid, int sig);\nint (*const util_killer)(int, int) = kill;\n' >> util/util.c
grep -q util_killer util/util.c
