set -eu
sed -i 's/^#include <stdlib.h>/#include <signal.h>\n#include <stdlib.h>/' util/util.c
printf '\nint (*const util_killer)(pid_t, int) = kill;\n' >> util/util.c
grep -q util_killer util/util.c
