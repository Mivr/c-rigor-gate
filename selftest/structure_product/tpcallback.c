/* The send callback handed to the vendored TLS library calls back into the library (mbedtls_ssl_write). */
#include <stddef.h>

#include "mbedtls/ssl.h"

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
    return mbedtls_ssl_write((mbedtls_ssl_context *)ctx, buf, len);
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
    (void)ctx;
    (void)buf;
    return (int)len;
}

int tp_connect(mbedtls_ssl_context *ssl)
{
    mbedtls_ssl_set_bio(ssl, ssl, bio_send, bio_recv, NULL);
    return 0;
}
