set -eu
sed -i 's/^#include <stdlib.h>/#include <signal.h>\n#include <stdlib.h>/' util/util.c
printf '\nint util_stop(int pid);\nint util_stop(int pid) { return kill(pid, 0); }\n' >> util/util.c
grep -q 'kill(pid' util/util.c
