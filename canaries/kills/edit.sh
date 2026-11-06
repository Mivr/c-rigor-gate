set -eu
printf '\nint kill(int pid, int sig);\nint core_stop(int pid);\nint core_stop(int pid) { return kill(pid, 0); }\n' >> core/core.c
