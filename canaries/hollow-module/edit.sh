set -eu
cat > core/core.h <<'EOT'
#ifndef CORE_H
#define CORE_H

extern const int core_marker;
static inline int core_add(int a, int b) { return a + b; }
static inline int core_sign(int value) {
    if (value < 0) {
        return -1;
    }
    if (value > 0) {
        return 1;
    }
    return 0;
}

#endif
EOT
printf '#include "core.h"\n\nconst int core_marker = 1;\n' > core/core.c
