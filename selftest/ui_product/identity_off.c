/* The toy's builds WITHOUT scene identity (U24): `identity` is `err identity unsupported`, the greeting does not
 * announce it. */
#include "ui/model/model.h"

bool uim_identity_supported(void)
{
    return false;
}

bool uim_identity(uim_t *m, uim_buf_t *out)
{
    (void)m;
    out->len = 0;
    return false;
}
