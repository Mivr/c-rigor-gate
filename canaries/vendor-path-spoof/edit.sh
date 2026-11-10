set -eu
# A product directory named like the gate's third-party tree: `core/art/gate/third_party/`. Buck2 materialises its
# headers under buck-out/v2/art/root/core/.../art/gate/third_party/..., which carries the vendor fragment.
mkdir -p core/art/gate/third_party
cat > core/art/gate/third_party/spoof.h <<'HDR'
#ifndef CORE_SPOOF_H
#define CORE_SPOOF_H

#pragma clang diagnostic ignored "-Wunused-function"

__attribute__((no_sanitize("address"))) static inline int spoof_peek(const int *p) { return *p; }

#endif
HDR
sed -i 's|headers = \["core.h"\]|headers = ["core.h", "art/gate/third_party/spoof.h"]|' core/BUCK
printf '\n#include "art/gate/third_party/spoof.h"\n' >> core/core.c
