set -eu
printf '\nint kill(int pid, int sig);\nint util_stop(int pid);\nint util_stop(int pid) { return kill(pid, 0); }\n' >> util/util.c
grep -q 'kill(pid' util/util.c
