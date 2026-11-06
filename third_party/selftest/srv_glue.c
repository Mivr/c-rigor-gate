/* Self-test server (T009). Compiled against the renamed private copy of the library. */
#include "srv_rename.h"

#include <string.h>

#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/pk.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"
#include "srv_glue.h"
#include "srv_pki.h"

static mbedtls_ssl_context g_ssl;
static mbedtls_ssl_config g_conf;
static mbedtls_entropy_context g_entropy;
static mbedtls_ctr_drbg_context g_drbg;
static mbedtls_x509_crt g_cert;
static mbedtls_pk_context g_key;

static unsigned char g_in[32768];
static size_t g_in_len;
static size_t g_in_pos;
static unsigned char g_out[32768];
static size_t g_out_len;
static int g_up;
static int g_done;

const char *srv_ca_pem(void)
{
    return srv_ca_pem_text;
}

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
        return MBEDTLS_ERR_SSL_WANT_READ;
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

int srv_put(const unsigned char *data, size_t len)
{
    if (len > sizeof g_in - g_in_len) {
        return -1;
    }
    memcpy(g_in + g_in_len, data, len);
    g_in_len += len;
    return 0;
}

size_t srv_take(unsigned char *out, size_t cap)
{
    size_t n = g_out_len < cap ? g_out_len : cap;
    memcpy(out, g_out, n);
    memmove(g_out, g_out + n, g_out_len - n);
    g_out_len -= n;
    return n;
}

static int load_identity(int use_rsa)
{
    const char *cert = use_rsa ? srv_rsa_cert_pem : srv_ec_cert_pem;
    const char *key = use_rsa ? srv_rsa_key_pem : srv_ec_key_pem;
    int ret = mbedtls_x509_crt_parse(&g_cert, (const unsigned char *) cert, strlen(cert) + 1);
    if (ret != 0) {
        return ret;
    }
    return mbedtls_pk_parse_key(&g_key, (const unsigned char *) key, strlen(key) + 1, NULL, 0,
                                mbedtls_ctr_drbg_random, &g_drbg);
}

static int setup(int use_rsa, int tls12_only)
{
    int ret = mbedtls_ctr_drbg_seed(&g_drbg, mbedtls_entropy_func, &g_entropy, NULL, 0);
    if (ret == 0) {
        ret = load_identity(use_rsa);
    }
    if (ret == 0) {
        ret = mbedtls_ssl_config_defaults(&g_conf, MBEDTLS_SSL_IS_SERVER, MBEDTLS_SSL_TRANSPORT_STREAM,
                                          MBEDTLS_SSL_PRESET_DEFAULT);
    }
    if (ret != 0) {
        return ret;
    }
    mbedtls_ssl_conf_rng(&g_conf, mbedtls_ctr_drbg_random, &g_drbg);
    mbedtls_ssl_conf_authmode(&g_conf, MBEDTLS_SSL_VERIFY_NONE);
    if (tls12_only) {
        mbedtls_ssl_conf_max_tls_version(&g_conf, MBEDTLS_SSL_VERSION_TLS1_2);
    }
    ret = mbedtls_ssl_conf_own_cert(&g_conf, &g_cert, &g_key);
    if (ret == 0) {
        ret = mbedtls_ssl_setup(&g_ssl, &g_conf);
    }
    mbedtls_ssl_set_bio(&g_ssl, NULL, bio_send, bio_recv, NULL);
    return ret;
}

int srv_start(int use_rsa, int tls12_only)
{
    int ret;
    g_in_len = g_in_pos = g_out_len = 0;
    g_done = 0;
    mbedtls_ssl_init(&g_ssl);
    mbedtls_ssl_config_init(&g_conf);
    mbedtls_entropy_init(&g_entropy);
    mbedtls_ctr_drbg_init(&g_drbg);
    mbedtls_x509_crt_init(&g_cert);
    mbedtls_pk_init(&g_key);
    g_up = 1;
    ret = (int) psa_crypto_init();
    if (ret == 0) {
        ret = setup(use_rsa, tls12_only);
    }
    return ret;
}

void srv_stop(void)
{
    if (g_up) {
        mbedtls_ssl_free(&g_ssl);
        mbedtls_ssl_config_free(&g_conf);
        mbedtls_ctr_drbg_free(&g_drbg);
        mbedtls_entropy_free(&g_entropy);
        mbedtls_x509_crt_free(&g_cert);
        mbedtls_pk_free(&g_key);
        mbedtls_psa_crypto_free();
        g_up = 0;
    }
}

int srv_established(void)
{
    return g_done;
}

const char *srv_version(void)
{
    return mbedtls_ssl_get_version(&g_ssl);
}

static int echo(void)
{
    unsigned char buf[2048];
    int n = mbedtls_ssl_read(&g_ssl, buf, sizeof buf);
    if (n == MBEDTLS_ERR_SSL_WANT_READ || n == MBEDTLS_ERR_SSL_WANT_WRITE) {
        return 0;
    }
    if (n <= 0) {
        return n == 0 ? MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY : n;
    }
    n = mbedtls_ssl_write(&g_ssl, buf, (size_t) n);
    return n < 0 ? n : 0;
}

int srv_step(void)
{
    int ret;
    if (!g_done) {
        ret = mbedtls_ssl_handshake(&g_ssl);
        if (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE) {
            return 0;
        }
        if (ret != 0) {
            return ret;
        }
        g_done = 1;
    }
    return echo();
}
