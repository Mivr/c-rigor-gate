/* Throwaway product test (T009 self-test): the gate's client library against an in-memory server.
 * Product rules apply to this file (sealed flags, no ambient clock, static memory). */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "ctest/ctest.h"
#include "mbedtls/ctr_drbg.h"
#include "mbedtls/entropy.h"
#include "mbedtls/platform_time.h"
#include "mbedtls/ssl.h"
#include "mbedtls/version.h"
#include "mbedtls/x509_crt.h"
#include "psa/crypto.h"
#include "srv_glue.h"

#define NOW_2027 1798761600L
#define NOW_2130 5049129600L
#define HOST "tls.selftest.invalid"

static mbedtls_ssl_context g_ssl;
static mbedtls_ssl_config g_conf;
static mbedtls_entropy_context g_entropy;
static mbedtls_ctr_drbg_context g_drbg;
static mbedtls_x509_crt g_ca;
static unsigned char g_out[32768];
static size_t g_out_len;
static unsigned char g_in[32768];
static size_t g_in_len;
static size_t g_in_pos;

static mbedtls_time_t clock_2027(mbedtls_time_t *timer)
{
    if (timer != NULL) {
        *timer = NOW_2027;
    }
    return NOW_2027;
}

static mbedtls_time_t clock_2130(mbedtls_time_t *timer)
{
    if (timer != NULL) {
        *timer = NOW_2130;
    }
    return NOW_2130;
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

/* Move bytes both ways between the client and the in-memory server. */
static void deliver(void)
{
    if (g_out_len > 0) {
        (void) srv_put(g_out, g_out_len);
        g_out_len = 0;
    }
    g_in_len += srv_take(g_in + g_in_len, sizeof g_in - g_in_len);
}

typedef struct {
    int trust_ca;
    int client_tls12_only;
    const char *host;
} client_opts_t;

static int client_start(const client_opts_t *opts)
{
    const char *pem = srv_ca_pem();
    int ret;
    g_out_len = g_in_len = g_in_pos = 0;
    mbedtls_ssl_init(&g_ssl);
    mbedtls_ssl_config_init(&g_conf);
    mbedtls_entropy_init(&g_entropy);
    mbedtls_ctr_drbg_init(&g_drbg);
    mbedtls_x509_crt_init(&g_ca);
    ret = (int) psa_crypto_init();
    if (ret == 0) {
        ret = mbedtls_ctr_drbg_seed(&g_drbg, mbedtls_entropy_func, &g_entropy, NULL, 0);
    }
    if (ret == 0 && opts->trust_ca) {
        ret = mbedtls_x509_crt_parse(&g_ca, (const unsigned char *) pem, strlen(pem) + 1);
    }
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
    if (opts->client_tls12_only) {
        mbedtls_ssl_conf_max_tls_version(&g_conf, MBEDTLS_SSL_VERSION_TLS1_2);
    }
    ret = mbedtls_ssl_setup(&g_ssl, &g_conf);
    if (ret == 0) {
        ret = mbedtls_ssl_set_hostname(&g_ssl, opts->host);
    }
    mbedtls_ssl_set_bio(&g_ssl, NULL, bio_send, bio_recv, NULL);
    return ret;
}

static void client_stop(void)
{
    mbedtls_ssl_free(&g_ssl);
    mbedtls_ssl_config_free(&g_conf);
    mbedtls_ctr_drbg_free(&g_drbg);
    mbedtls_entropy_free(&g_entropy);
    mbedtls_x509_crt_free(&g_ca);
    mbedtls_psa_crypto_free();
    srv_stop();
}

/* Drive both ends until the client handshake finishes or fails; returns the client's result. */
static int handshake(void)
{
    int round;
    for (round = 0; round < 64; round++) {
        int ret = mbedtls_ssl_handshake(&g_ssl);
        if (ret != MBEDTLS_ERR_SSL_WANT_READ && ret != MBEDTLS_ERR_SSL_WANT_WRITE) {
            deliver();
            return ret;
        }
        deliver();
        (void) srv_step();
        deliver();
    }
    return MBEDTLS_ERR_SSL_TIMEOUT;
}

static int echo_round_trip(const char *text)
{
    unsigned char back[64];
    size_t want = strlen(text);
    size_t got = 0;
    int round;
    int ret = mbedtls_ssl_write(&g_ssl, (const unsigned char *) text, want);
    if (ret < 0 || (size_t) ret != want) {
        return -1;
    }
    for (round = 0; round < 16 && got < want; round++) {
        deliver();
        (void) srv_step();
        deliver();
        ret = mbedtls_ssl_read(&g_ssl, back + got, sizeof back - got);
        if (ret > 0) {
            got += (size_t) ret;
        } else if (ret != MBEDTLS_ERR_SSL_WANT_READ) {
            return -2;
        }
    }
    return got == want && memcmp(back, text, want) == 0 ? 0 : -3;
}

/* Handshake against a server with the given shape; checks the negotiated version and the echo. */
static void full_session(ctest_t *t, int use_rsa, int srv_tls12_only, int cli_tls12_only, const char *version)
{
    client_opts_t opts = {1, cli_tls12_only, HOST};
    mbedtls_platform_set_time(clock_2027);
    CHECK_EQ_I64(t, srv_start(use_rsa, srv_tls12_only), 0);
    CHECK_EQ_I64(t, client_start(&opts), 0);
    CHECK_EQ_I64(t, handshake(), 0);
    CHECK_EQ_STR(t, mbedtls_ssl_get_version(&g_ssl), version);
    CHECK_EQ_STR(t, srv_version(), version);
    CHECK_EQ_U64(t, mbedtls_ssl_get_verify_result(&g_ssl), 0);
    CHECK_EQ_I64(t, echo_round_trip("hello over the gate-owned library"), 0);
    client_stop();
}

/* Handshake that must be refused; returns the certificate verification flags. */
static uint32_t refused(ctest_t *t, const client_opts_t *opts, mbedtls_time_t (*clock)(mbedtls_time_t *))
{
    uint32_t flags;
    if (clock != NULL) {
        mbedtls_platform_set_time(clock);
    }
    CHECK_EQ_I64(t, srv_start(0, 0), 0);
    CHECK_EQ_I64(t, client_start(opts), 0);
    CHECK_EQ_I64(t, handshake(), MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
    flags = mbedtls_ssl_get_verify_result(&g_ssl);
    client_stop();
    return flags;
}

static void t_tls13_ecdsa(ctest_t *t) { full_session(t, 0, 0, 0, "TLSv1.3"); }
static void t_tls13_rsa(ctest_t *t) { full_session(t, 1, 0, 0, "TLSv1.3"); }
static void t_tls12_server_only(ctest_t *t) { full_session(t, 0, 1, 0, "TLSv1.2"); }
static void t_tls12_client_only(ctest_t *t) { full_session(t, 1, 0, 1, "TLSv1.2"); }

static void t_wrong_host(ctest_t *t)
{
    client_opts_t opts = {1, 0, "other.selftest.invalid"};
    CHECK(t, (refused(t, &opts, clock_2027) & MBEDTLS_X509_BADCERT_CN_MISMATCH) != 0);
}

static void t_untrusted_ca(ctest_t *t)
{
    client_opts_t opts = {0, 0, HOST};
    CHECK(t, (refused(t, &opts, clock_2027) & MBEDTLS_X509_BADCERT_NOT_TRUSTED) != 0);
}

/* Nothing injects a clock: the library's default is time 0, so the certificate is not yet valid. */
static void t_clock_not_injected(ctest_t *t)
{
    client_opts_t opts = {1, 0, HOST};
    CHECK(t, (refused(t, &opts, NULL) & MBEDTLS_X509_BADCERT_FUTURE) != 0);
}

static void t_clock_injected_late(ctest_t *t)
{
    client_opts_t opts = {1, 0, HOST};
    CHECK(t, (refused(t, &opts, clock_2130) & MBEDTLS_X509_BADCERT_EXPIRED) != 0);
}

static void t_entropy_is_live(ctest_t *t)
{
    unsigned char a[32];
    unsigned char b[32];
    mbedtls_entropy_init(&g_entropy);
    CHECK_EQ_I64(t, mbedtls_entropy_func(&g_entropy, a, sizeof a), 0);
    CHECK_EQ_I64(t, mbedtls_entropy_func(&g_entropy, b, sizeof b), 0);
    CHECK(t, memcmp(a, b, sizeof a) != 0);
    mbedtls_entropy_free(&g_entropy);
}

static void t_pinned_version(ctest_t *t)
{
    char version[18];
    mbedtls_version_get_string(version);
    CHECK_EQ_STR(t, version, "3.6.7");
}

CTEST_SUITE("tls", { "tls13_ecdsa", t_tls13_ecdsa }, { "tls13_rsa", t_tls13_rsa },
            { "tls12_server_only", t_tls12_server_only }, { "tls12_client_only", t_tls12_client_only },
            { "wrong_host", t_wrong_host }, { "untrusted_ca", t_untrusted_ca },
            { "clock_not_injected", t_clock_not_injected }, { "clock_injected_late", t_clock_injected_late },
            { "entropy_is_live", t_entropy_is_live }, { "pinned_version", t_pinned_version })
