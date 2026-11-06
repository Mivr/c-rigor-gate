set -eu
mkdir -p tools
printf '#!/bin/sh\necho ran > "%s/ran"\nexit 1\n' "$CANARY_SCRATCH" > tools/buck2
chmod +x tools/buck2
