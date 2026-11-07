set -eu
cat >> core/BUCK <<'EOF'

# T070: tpw links a third-party library (mbedtls, cell gate); tpm is a pure module whose test also links tpw.
c_library(
    name = "tpw",
    srcs = ["tpw.c"],
    headers = ["tpw.h"],
    deps = ["gate//third_party/mbedtls:mbedtls"],
    visibility = ["PUBLIC"],
)

c_test(name = "tpw_test", srcs = ["tpw_test.c"], deps = [":tpw"])

c_library(name = "tpm", srcs = ["tpm.c"], headers = ["tpm.h"], visibility = ["PUBLIC"])

c_test(name = "tpm_test", srcs = ["tpm_test.c"], deps = [":tpm", ":tpw"])
EOF
printf '#ifndef TPW_H\n#define TPW_H\n#include <stddef.h>\nsize_t tpw_b64_len(size_t n);\n#endif\n' > core/tpw.h
cat > core/tpw.c <<'EOF'
#include "tpw.h"

#include "mbedtls/base64.h"

size_t tpw_b64_len(size_t n)
{
    size_t olen = 0;
    unsigned char dummy = 0;
    (void)mbedtls_base64_encode(NULL, 0, &olen, &dummy, n);
    return olen;
}
EOF
cat > core/tpw_test.c <<'EOF'
#include "ctest/ctest.h"
#include "tpw.h"

static void t_len(ctest_t *t)
{
    CHECK_EQ_I64(t, (long long)tpw_b64_len(0), 0);
    CHECK_EQ_I64(t, (long long)tpw_b64_len(3), 5);
    CHECK_EQ_I64(t, (long long)tpw_b64_len(4), 9);
}

CTEST_SUITE("tpw", { "len", t_len })
EOF
printf '#ifndef TPM_H\n#define TPM_H\nint tpm_clamp(int x);\nint tpm_double(int x);\n#endif\n' > core/tpm.h
cat > core/tpm.c <<'EOF'
#include "tpm.h"

int tpm_clamp(int x)
{
    if (x > 100) {
        return 100;
    }
    return x;
}

int tpm_double(int x)
{
    return x + x;
}
EOF
cat > core/tpm_test.c <<'EOF'
#include "ctest/ctest.h"
#include "tpm.h"
#include "tpw.h"

/* The test links tpw and, through it, the third-party library: the mutants of tpm must link it too.
   tpm_clamp is deliberately under-tested (the boundary 100 is never checked): its mutants survive. */
static void t_clamp(ctest_t *t)
{
    CHECK_EQ_I64(t, tpm_clamp(5), 5);
    CHECK_EQ_I64(t, tpm_clamp(500), 100);
}

static void t_double(ctest_t *t)
{
    CHECK_EQ_I64(t, tpm_double(21), 42);
    CHECK_EQ_I64(t, (long long)tpw_b64_len(3), 5);
}

CTEST_SUITE("tpm", { "clamp", t_clamp }, { "double", t_double })
