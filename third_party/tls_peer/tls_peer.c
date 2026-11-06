/* TLS test peer (T012, from the T009 self-test server). Compiled against the renamed private copy of
 * the library (every exported symbol is prefixed srv_ by srv_rename.h and by the archive). */
#include "srv_rename.h"

#include <string.h>

#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/pk.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"
#include "tls_peer.h"
#include "tls_peer_pki.h"

/* Not in a public header of the library, but exported: sends one alert record. */
int mbedtls_ssl_send_alert_message(mbedtls_ssl_context *ssl, unsigned char level, unsigned char message);

#define IO_CAP 32768
#define RX_CAP 4096

static mbedtls_ssl_context g_ssl;
static mbedtls_ssl_config g_conf;
static mbedtls_entropy_context g_entropy;
static mbedtls_ctr_drbg_context g_drbg;
static mbedtls_x509_crt g_cert;
static mbedtls_pk_context g_key;

static unsigned char g_in[IO_CAP];
static size_t g_in_len;
static size_t g_in_pos;
static unsigned char g_out[IO_CAP];
static size_t g_out_len;
static unsigned char g_rx[RX_CAP];
static size_t g_rx_len;
static int g_up;
static int g_done;
static int g_error;
static int g_closed;

static const char *const g_cert_pem[TLS_PEER_IDENTITY_COUNT] = {
    tls_peer_pem_ec_valid_crt, tls_peer_pem_rsa_valid_crt, tls_peer_pem_expired_crt,
    tls_peer_pem_not_yet_valid_crt, tls_peer_pem_wrong_host_crt, tls_peer_pem_unknown_ca_crt,
    tls_peer_pem_chain_crt};
static const char *const g_key_pem[TLS_PEER_IDENTITY_COUNT] = {
    tls_peer_pem_ec_valid_key, tls_peer_pem_rsa_valid_key, tls_peer_pem_expired_key,
    tls_peer_pem_not_yet_valid_key, tls_peer_pem_wrong_host_key, tls_peer_pem_unknown_ca_key,
    tls_peer_pem_chain_key};

const char *tls_peer_ca_pem(void)
{
    return tls_peer_pem_root_ca;
}

const char *tls_peer_other_ca_pem(void)
{
    return tls_peer_pem_other_ca;
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

int tls_peer_put(const unsigned char *data, size_t len)
{
    if (!g_up) {
        return TLS_PEER_ERR_NOT_STARTED;
    }
    if (len > sizeof g_in - g_in_len) {
        return TLS_PEER_ERR_FULL;
    }
    if (len > 0) {
        memcpy(g_in + g_in_len, data, len);
    }
    g_in_len += len;
    return 0;
}

size_t tls_peer_take(unsigned char *out, size_t cap)
{
    size_t n = g_out_len < cap ? g_out_len : cap;
    if (n > 0) {
        memcpy(out, g_out, n);
        memmove(g_out, g_out + n, g_out_len - n);
        g_out_len -= n;
    }
    return n;
}

static int load_identity(tls_peer_identity_t identity)
{
    const char *cert = g_cert_pem[identity];
    const char *key = g_key_pem[identity];
    int ret = mbedtls_x509_crt_parse(&g_cert, (const unsigned char *) cert, strlen(cert) + 1);
    if (ret != 0) {
        return ret;
    }
    return mbedtls_pk_parse_key(&g_key, (const unsigned char *) key, strlen(key) + 1, NULL, 0,
                                mbedtls_ctr_drbg_random, &g_drbg);
}

static int setup(tls_peer_identity_t identity, tls_peer_versions_t versions)
{
    int ret = mbedtls_ctr_drbg_seed(&g_drbg, mbedtls_entropy_func, &g_entropy, NULL, 0);
    if (ret == 0) {
        ret = load_identity(identity);
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
    if (versions == TLS_PEER_TLS12_ONLY) {
        mbedtls_ssl_conf_max_tls_version(&g_conf, MBEDTLS_SSL_VERSION_TLS1_2);
    }
    ret = mbedtls_ssl_conf_own_cert(&g_conf, &g_cert, &g_key);
    if (ret == 0) {
        ret = mbedtls_ssl_setup(&g_ssl, &g_conf);
    }
    mbedtls_ssl_set_bio(&g_ssl, NULL, bio_send, bio_recv, NULL);
    return ret;
}

int tls_peer_start(tls_peer_identity_t identity, tls_peer_versions_t versions)
{
    int ret;
    if ((unsigned) identity >= (unsigned) TLS_PEER_IDENTITY_COUNT ||
        (versions != TLS_PEER_BOTH_VERSIONS && versions != TLS_PEER_TLS12_ONLY)) {
        return TLS_PEER_ERR_BAD_ARGUMENT;
    }
    tls_peer_stop();
    g_in_len = g_in_pos = g_out_len = g_rx_len = 0;
    g_done = g_error = g_closed = 0;
    mbedtls_ssl_init(&g_ssl);
    mbedtls_ssl_config_init(&g_conf);
    mbedtls_entropy_init(&g_entropy);
    mbedtls_ctr_drbg_init(&g_drbg);
    mbedtls_x509_crt_init(&g_cert);
    mbedtls_pk_init(&g_key);
    g_up = 1;
    ret = (int) psa_crypto_init();
    if (ret == 0) {
        ret = setup(identity, versions);
    }
    if (ret != 0) {
        tls_peer_stop();
    }
    return ret;
}

void tls_peer_stop(void)
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

int tls_peer_established(void)
{
    return g_up && g_done;
}

const char *tls_peer_version(void)
{
    return tls_peer_established() ? mbedtls_ssl_get_version(&g_ssl) : NULL;
}

int tls_peer_error(void)
{
    return g_error;
}

int tls_peer_client_closed(void)
{
    return g_closed;
}

size_t tls_peer_received(unsigned char *out, size_t cap)
{
    size_t n = g_rx_len < cap ? g_rx_len : cap;
    if (n > 0) {
        memcpy(out, g_rx, n);
        memmove(g_rx, g_rx + n, g_rx_len - n);
        g_rx_len -= n;
    }
    return n;
}

static int fail_with(int ret)
{
    g_error = ret;
    return ret;
}

/* Read what the client sent into the receive queue; 0, or the error that ended the session. */
static int drain(void)
{
    while (g_rx_len < sizeof g_rx) {
        int n = mbedtls_ssl_read(&g_ssl, g_rx + g_rx_len, sizeof g_rx - g_rx_len);
        if (n == MBEDTLS_ERR_SSL_WANT_READ || n == MBEDTLS_ERR_SSL_WANT_WRITE) {
            return 0;
        }
        if (n == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY || n == 0) {
            g_closed = 1;
            return 0;
        }
        if (n < 0) {
            return fail_with(n);
        }
        g_rx_len += (size_t) n;
    }
    return 0;
}

int tls_peer_step(void)
{
    int ret;
    if (!g_up) {
        return TLS_PEER_ERR_NOT_STARTED;
    }
    if (g_error != 0) {
        return g_error;
    }
    if (!g_done) {
        ret = mbedtls_ssl_handshake(&g_ssl);
        if (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE) {
            return 0;
        }
        if (ret != 0) {
            return fail_with(ret);
        }
        g_done = 1;
    }
    return g_closed ? 0 : drain();
}

int tls_peer_send(const unsigned char *data, size_t len)
{
    int ret;
    if (!tls_peer_established() || g_error != 0) {
        return TLS_PEER_ERR_NOT_STARTED;
    }
    ret = mbedtls_ssl_write(&g_ssl, data, len);
    if (ret < 0) {
        return ret;
    }
    return (size_t) ret == len ? 0 : TLS_PEER_ERR_FULL;
}

int tls_peer_close_notify(void)
{
    if (!tls_peer_established() || g_error != 0) {
        return TLS_PEER_ERR_NOT_STARTED;
    }
    return mbedtls_ssl_close_notify(&g_ssl);
}

int tls_peer_alert(tls_peer_alert_t alert)
{
    switch (alert) {
    case TLS_PEER_ALERT_UNEXPECTED_MESSAGE:
    case TLS_PEER_ALERT_BAD_RECORD_MAC:
    case TLS_PEER_ALERT_HANDSHAKE_FAILURE:
    case TLS_PEER_ALERT_DECODE_ERROR:
    case TLS_PEER_ALERT_PROTOCOL_VERSION:
    case TLS_PEER_ALERT_INTERNAL_ERROR:
        break;
    default:
        return TLS_PEER_ERR_BAD_ARGUMENT;
    }
    if (!g_up) {
        return TLS_PEER_ERR_NOT_STARTED;
    }
    if (g_error != 0) {
        return g_error;
    }
    g_error = MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE;
    return mbedtls_ssl_send_alert_message(&g_ssl, MBEDTLS_SSL_ALERT_LEVEL_FATAL, (unsigned char) alert);
}
