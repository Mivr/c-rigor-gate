/* The mbedTLS shape: callbacks registered with the vendored library that never call into it. */
#include <stddef.h>

#include "mbedtls/ssl.h"

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
    (void)ctx;
    (void)buf;
    return (int)len;
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
    (void)ctx;
    (void)buf;
    return (int)len;
}

int tp_connect(mbedtls_ssl_context *ssl)
{
    mbedtls_ssl_set_bio(ssl, NULL, bio_send, bio_recv, NULL);
    return mbedtls_ssl_handshake(ssl);
}

/* Like a port's ops table: tp_connect's address is taken and it reaches the registering call. The library can
 * only call back what it was handed (bio_send, bio_recv), so this is no cycle. */
struct tp_ops {
    int (*connect)(mbedtls_ssl_context *);
};

const struct tp_ops tp_table = { tp_connect };
