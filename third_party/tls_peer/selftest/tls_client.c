/* Throwaway product module of the TLS peer self-test (see tls_client.h). */
#include "tls_client.h"

#include <string.h>

#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"

#define IO_CAP 32768

static mbedtls_ssl_context g_ssl;
static mbedtls_ssl_config g_conf;
static mbedtls_entropy_context g_entropy;
static mbedtls_ctr_drbg_context g_drbg;
static mbedtls_x509_crt g_ca;
static unsigned char g_out[IO_CAP];
static size_t g_out_len;
static unsigned char g_in[IO_CAP];
static size_t g_in_len;
static size_t g_in_pos;
static int g_eof;
static int g_up;

static int bio_send(void *ctx, const unsigned char *buf, size_t len)
{
    (void) ctx;
    if (len > sizeof g_out - g_out_len) {
        return MBEDTLS_ERR_SSL_WANT_WRITE;
    }
    memcpy(g_out + g_out_len, buf, len);
    g_out_len += len;
    return (int) len;
}

static int bio_recv(void *ctx, unsigned char *buf, size_t len)
{
    size_t n = g_in_len - g_in_pos;
    (void) ctx;
    if (n == 0) {
        return g_eof ? 0 : MBEDTLS_ERR_SSL_WANT_READ;
    }
    if (n > len) {
        n = len;
    }
    memcpy(buf, g_in + g_in_pos, n);
    g_in_pos += n;
    if (g_in_pos == g_in_len) {
        g_in_pos = 0;
        g_in_len = 0;
    }
    return (int) n;
}

size_t tls_client_outgoing(unsigned char *out, size_t cap)
{
    size_t n = g_out_len < cap ? g_out_len : cap;
    memcpy(out, g_out, n);
    memmove(g_out, g_out + n, g_out_len - n);
    g_out_len -= n;
    return n;
}

void tls_client_incoming(const unsigned char *data, size_t len)
{
    size_t room = sizeof g_in - g_in_len;
    size_t n = len < room ? len : room;
    memcpy(g_in + g_in_len, data, n);
    g_in_len += n;
}

void tls_client_eof(void)
{
    g_eof = 1;
}

static int configure(const char *ca_pem, const char *host, int tls12_only)
{
    int ret = mbedtls_x509_crt_parse(&g_ca, (const unsigned char *) ca_pem, strlen(ca_pem) + 1U);
    if (ret == 0) {
        ret = mbedtls_ssl_config_defaults(&g_conf, MBEDTLS_SSL_IS_CLIENT, MBEDTLS_SSL_TRANSPORT_STREAM,
                                          MBEDTLS_SSL_PRESET_DEFAULT);
    }
    if (ret != 0) {
        return ret;
    }
    mbedtls_ssl_conf_authmode(&g_conf, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(&g_conf, &g_ca, NULL);
    mbedtls_ssl_conf_rng(&g_conf, mbedtls_ctr_drbg_random, &g_drbg);
    if (tls12_only != 0) {
        mbedtls_ssl_conf_max_tls_version(&g_conf, MBEDTLS_SSL_VERSION_TLS1_2);
    }
    ret = mbedtls_ssl_setup(&g_ssl, &g_conf);
    if (ret == 0) {
        ret = mbedtls_ssl_set_hostname(&g_ssl, host);
    }
    mbedtls_ssl_set_bio(&g_ssl, NULL, bio_send, bio_recv, NULL);
    return ret;
}

int tls_client_start(const char *ca_pem, const char *host, int tls12_only)
{
    int ret;
    tls_client_stop();
    g_out_len = 0;
    g_in_len = 0;
    g_in_pos = 0;
    g_eof = 0;
    mbedtls_ssl_init(&g_ssl);
    mbedtls_ssl_config_init(&g_conf);
    mbedtls_entropy_init(&g_entropy);
    mbedtls_ctr_drbg_init(&g_drbg);
    mbedtls_x509_crt_init(&g_ca);
    g_up = 1;
    ret = (int) psa_crypto_init();
    if (ret == 0) {
        ret = mbedtls_ctr_drbg_seed(&g_drbg, mbedtls_entropy_func, &g_entropy, NULL, 0);
    }
    if (ret == 0) {
        ret = configure(ca_pem, host, tls12_only);
    }
    return ret;
}

void tls_client_stop(void)
{
    if (g_up != 0) {
        mbedtls_ssl_free(&g_ssl);
        mbedtls_ssl_config_free(&g_conf);
        mbedtls_ctr_drbg_free(&g_drbg);
        mbedtls_entropy_free(&g_entropy);
        mbedtls_x509_crt_free(&g_ca);
        mbedtls_psa_crypto_free();
        g_up = 0;
    }
}

int tls_client_handshake(void)
{
    return mbedtls_ssl_handshake(&g_ssl);
}

int tls_client_write(const unsigned char *data, size_t len)
{
    return mbedtls_ssl_write(&g_ssl, data, len);
}

int tls_client_read(unsigned char *out, size_t cap)
{
    int ret = mbedtls_ssl_read(&g_ssl, out, cap);
    if (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE) {
        return TLS_CLIENT_AGAIN;
    }
    if (ret == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY) {
        return TLS_CLIENT_CLOSED;
    }
    /* mbedTLS reports a transport end of file as 0 (or CONN_EOF): the peer never said close_notify. */
    return (ret == 0 || ret == MBEDTLS_ERR_SSL_CONN_EOF) ? TLS_CLIENT_TRUNCATED : ret;
}

int tls_client_close(void)
{
    return mbedtls_ssl_close_notify(&g_ssl);
}

uint32_t tls_client_verify_flags(void)
{
    return mbedtls_ssl_get_verify_result(&g_ssl);
}

const char *tls_client_version(void)
{
    return mbedtls_ssl_get_version(&g_ssl);
}
