/* Throwaway product test of the TLS peer self-test: the real client-only library (through tls_client)
 * against the gate-owned in-memory peer. Product rules apply to this file (sealed flags, no ambient
 * clock, static memory). */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "ctest/ctest.h"
#include "mbedtls/entropy.h"
#include "mbedtls/platform_time.h"
#include "mbedtls/ssl.h"
#include "mbedtls/version.h"
#include "mbedtls/x509_crt.h"
#include "tls_client.h"
#include "tls_peer.h"

static mbedtls_time_t g_now;
static unsigned char g_buf[32768];
static unsigned char g_data[4096];

static mbedtls_time_t clock_now(mbedtls_time_t *timer)
{
    if (timer != NULL) {
        *timer = g_now;
    }
    return g_now;
}

static void set_time(long seconds)
{
    g_now = (mbedtls_time_t) seconds;
    mbedtls_platform_set_time(clock_now);
}

/* Move bytes both ways between the client under test and the peer. */
static void pump(void)
{
    size_t n = tls_client_outgoing(g_buf, sizeof g_buf);
    if (n > 0) {
        (void) tls_peer_put(g_buf, n);
    }
    n = tls_peer_take(g_buf, sizeof g_buf);
    if (n > 0) {
        tls_client_incoming(g_buf, n);
    }
}

/* Drive both ends until the client handshake finishes or fails; returns the client's result. */
static int handshake(void)
{
    int round;
    for (round = 0; round < 64; round++) {
        int ret = tls_client_handshake();
        if (ret != MBEDTLS_ERR_SSL_WANT_READ && ret != MBEDTLS_ERR_SSL_WANT_WRITE) {
            pump();
            (void) tls_peer_step(); /* TLS 1.3: the peer is done only after the client's Finished */
            pump();
            return ret;
        }
        pump();
        (void) tls_peer_step();
        pump();
    }
    return MBEDTLS_ERR_SSL_TIMEOUT;
}

typedef struct {
    tls_peer_identity_t identity;
    tls_peer_versions_t peer_versions;
    int client_tls12_only;
    const char *host;
    const char *ca;
} setup_t;

static int open_session(const setup_t *s)
{
    int ret = tls_peer_start(s->identity, s->peer_versions);
    if (ret == 0) {
        ret = tls_client_start(s->ca, s->host, s->client_tls12_only);
    }
    return ret;
}

static void close_session(void)
{
    tls_client_stop();
    tls_peer_stop();
}

static setup_t good(tls_peer_identity_t identity)
{
    setup_t s = {identity, TLS_PEER_BOTH_VERSIONS, 0, TLS_PEER_HOST, NULL};
    s.ca = tls_peer_ca_pem();
    return s;
}

/* Application data both ways, checked byte for byte. */
static void exchange(ctest_t *t)
{
    unsigned char back[64];
    size_t got;
    int ret;
    CHECK_EQ_I64(t, tls_client_write((const unsigned char *) "ping from the client", 20), 20);
    pump();
    CHECK_EQ_I64(t, tls_peer_step(), 0);
    got = tls_peer_received(back, sizeof back);
    CHECK_EQ_U64(t, got, 20);
    CHECK_EQ_MEM(t, back, got, "ping from the client", 20);
    CHECK_EQ_I64(t, tls_peer_send((const unsigned char *) "pong from the peer", 18), 0);
    pump();
    ret = tls_client_read(back, sizeof back);
    CHECK_EQ_I64(t, ret, 18);
    CHECK_EQ_MEM(t, back, 18, "pong from the peer", 18);
}

static void full_session(ctest_t *t, tls_peer_identity_t identity, int peer12, int client12, const char *version)
{
    setup_t s = good(identity);
    s.peer_versions = peer12 != 0 ? TLS_PEER_TLS12_ONLY : TLS_PEER_BOTH_VERSIONS;
    s.client_tls12_only = client12;
    set_time(TLS_PEER_TIME_VALID);
    CHECK_EQ_I64(t, open_session(&s), 0);
    CHECK_EQ_I64(t, handshake(), 0);
    CHECK_EQ_I64(t, tls_peer_established(), 1);
    CHECK_EQ_STR(t, tls_client_version(), version);
    CHECK_EQ_STR(t, tls_peer_version(), version);
    CHECK_EQ_U64(t, tls_client_verify_flags(), 0);
    exchange(t);
    close_session();
}

/* A handshake that must be refused with exactly these certificate flags (now < 0: inject no clock). */
static void refused(ctest_t *t, const setup_t *s, long now, uint32_t flags)
{
    if (now >= 0) {
        set_time(now);
    }
    CHECK_EQ_I64(t, open_session(s), 0);
    CHECK_EQ_I64(t, handshake(), MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
    CHECK_EQ_U64(t, tls_client_verify_flags(), flags);
    CHECK_EQ_I64(t, tls_peer_established(), 0);
    close_session();
}

static void t_tls13_ecdsa(ctest_t *t) { full_session(t, TLS_PEER_EC_VALID, 0, 0, "TLSv1.3"); }
static void t_tls13_rsa(ctest_t *t) { full_session(t, TLS_PEER_RSA_VALID, 0, 0, "TLSv1.3"); }
static void t_tls12_peer_only(ctest_t *t) { full_session(t, TLS_PEER_EC_VALID, 1, 0, "TLSv1.2"); }
static void t_tls12_client_only(ctest_t *t) { full_session(t, TLS_PEER_RSA_VALID, 0, 1, "TLSv1.2"); }
static void t_chain_with_intermediate(ctest_t *t) { full_session(t, TLS_PEER_CHAIN, 0, 0, "TLSv1.3"); }

static void t_expired(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EXPIRED);
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_EXPIRED);
}

static void t_not_yet_valid(ctest_t *t)
{
    setup_t s = good(TLS_PEER_NOT_YET_VALID);
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_FUTURE);
}

static void t_wrong_host(ctest_t *t)
{
    setup_t s = good(TLS_PEER_WRONG_HOST);
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_CN_MISMATCH);
}

static void t_unknown_ca(ctest_t *t)
{
    setup_t s = good(TLS_PEER_UNKNOWN_CA);
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_NOT_TRUSTED);
}

static void t_other_ca_trusted_instead(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EC_VALID);
    s.ca = tls_peer_other_ca_pem();
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_NOT_TRUSTED);
}

static void t_wrong_name_asked_for(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EC_VALID);
    s.host = TLS_PEER_HOST_WRONG;
    refused(t, &s, TLS_PEER_TIME_VALID, MBEDTLS_X509_BADCERT_CN_MISMATCH);
}

/* The time values the header documents put the odd certificates inside their windows. */
static void t_time_windows(ctest_t *t)
{
    setup_t expired = good(TLS_PEER_EXPIRED);
    setup_t future = good(TLS_PEER_NOT_YET_VALID);
    set_time(TLS_PEER_TIME_EXPIRED_WINDOW);
    CHECK_EQ_I64(t, open_session(&expired), 0);
    CHECK_EQ_I64(t, handshake(), 0);
    close_session();
    set_time(TLS_PEER_TIME_FUTURE_WINDOW);
    CHECK_EQ_I64(t, open_session(&future), 0);
    CHECK_EQ_I64(t, handshake(), 0);
    close_session();
}

/* Nothing injects a clock: the library's default is time 0, so the certificate is not yet valid. */
static void t_clock_not_injected(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EC_VALID);
    refused(t, &s, -1, MBEDTLS_X509_BADCERT_FUTURE);
}

/* An established session on the default identity, for the stream tests. */
static void established(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EC_VALID);
    set_time(TLS_PEER_TIME_VALID);
    CHECK_EQ_I64(t, open_session(&s), 0);
    CHECK_EQ_I64(t, handshake(), 0);
}

static void t_client_close_notify(ctest_t *t)
{
    established(t);
    CHECK_EQ_I64(t, tls_peer_client_closed(), 0);
    CHECK_EQ_I64(t, tls_client_close(), 0);
    pump();
    CHECK_EQ_I64(t, tls_peer_step(), 0);
    CHECK_EQ_I64(t, tls_peer_client_closed(), 1);
    CHECK_EQ_I64(t, tls_peer_error(), 0);
    close_session();
}

static void t_peer_close_notify_is_eof(ctest_t *t)
{
    unsigned char back[16];
    established(t);
    CHECK_EQ_I64(t, tls_peer_send((const unsigned char *) "last words", 10), 0);
    CHECK_EQ_I64(t, tls_peer_close_notify(), 0);
    pump();
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), 10);
    CHECK_EQ_MEM(t, back, 10, "last words", 10);
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), TLS_CLIENT_CLOSED);
    close_session();
}

/* The connection ends without close_notify: the client must report an error, not a clean end. */
static void t_truncation_is_detected(ctest_t *t)
{
    unsigned char back[16];
    established(t);
    CHECK_EQ_I64(t, tls_peer_send((const unsigned char *) "cut short", 9), 0);
    pump();
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), 9);
    tls_peer_stop();
    tls_client_eof();
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), TLS_CLIENT_TRUNCATED);
    close_session();
}

/* The connection ends inside a record: no data from the cut record may be delivered. */
static void t_truncation_inside_a_record(ctest_t *t)
{
    unsigned char back[200];
    size_t n;
    established(t);
    memset(g_data, 'x', 100);
    CHECK_EQ_I64(t, tls_peer_send(g_data, 100), 0);
    n = tls_peer_take(g_buf, 40);
    CHECK_EQ_U64(t, n, 40);
    tls_client_incoming(g_buf, n);
    tls_client_eof();
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), TLS_CLIENT_TRUNCATED);
    close_session();
}

static void t_peer_fatal_alert(ctest_t *t)
{
    unsigned char back[16];
    established(t);
    CHECK_EQ_I64(t, tls_peer_alert(TLS_PEER_ALERT_INTERNAL_ERROR), 0);
    pump();
    CHECK_EQ_I64(t, tls_client_read(back, sizeof back), MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE);
    CHECK_EQ_I64(t, tls_peer_send(back, 1) != 0, 1);
    close_session();
}

static void t_peer_alert_during_the_handshake(ctest_t *t)
{
    setup_t s = good(TLS_PEER_EC_VALID);
    set_time(TLS_PEER_TIME_VALID);
    CHECK_EQ_I64(t, open_session(&s), 0);
    CHECK_EQ_I64(t, tls_client_handshake(), MBEDTLS_ERR_SSL_WANT_READ);
    pump();
    CHECK_EQ_I64(t, tls_peer_alert(TLS_PEER_ALERT_HANDSHAKE_FAILURE), 0);
    pump();
    CHECK_EQ_I64(t, handshake(), MBEDTLS_ERR_SSL_FATAL_ALERT_MESSAGE);
    close_session();
}

static void t_bulk_data_both_ways(ctest_t *t)
{
    size_t i;
    size_t got = 0;
    established(t);
    for (i = 0; i < sizeof g_data; i++) {
        g_data[i] = (unsigned char) (i * 7U);
    }
    CHECK_EQ_I64(t, tls_client_write(g_data, 3000), 3000);
    pump();
    CHECK_EQ_I64(t, tls_peer_step(), 0);
    CHECK_EQ_U64(t, tls_peer_received(g_buf, sizeof g_buf), 3000);
    CHECK_EQ_MEM(t, g_buf, 3000, g_data, 3000);
    CHECK_EQ_I64(t, tls_peer_send(g_data, 3000), 0);
    pump();
    for (i = 0; i < 4 && got < 3000; i++) {
        int ret = tls_client_read(g_buf + got, sizeof g_buf - got);
        CHECK(t, ret > 0);
        got += ret > 0 ? (size_t) ret : 3000U;
    }
    CHECK_EQ_U64(t, got, 3000);
    CHECK_EQ_MEM(t, g_buf, 3000, g_data, 3000);
    close_session();
}

static void t_peer_state_machine(ctest_t *t)
{
    unsigned char one = 1;
    tls_peer_stop();
    CHECK_EQ_I64(t, tls_peer_step(), TLS_PEER_ERR_NOT_STARTED);
    CHECK_EQ_I64(t, tls_peer_put(&one, 1), TLS_PEER_ERR_NOT_STARTED);
    CHECK_EQ_I64(t, tls_peer_send(&one, 1), TLS_PEER_ERR_NOT_STARTED);
    CHECK_EQ_I64(t, tls_peer_alert(TLS_PEER_ALERT_INTERNAL_ERROR), TLS_PEER_ERR_NOT_STARTED);
    CHECK_EQ_I64(t, tls_peer_start(TLS_PEER_IDENTITY_COUNT, TLS_PEER_BOTH_VERSIONS), TLS_PEER_ERR_BAD_ARGUMENT);
    CHECK_EQ_I64(t, tls_peer_start(TLS_PEER_EC_VALID, (tls_peer_versions_t) 7), TLS_PEER_ERR_BAD_ARGUMENT);
    CHECK_EQ_I64(t, tls_peer_start(TLS_PEER_EC_VALID, TLS_PEER_BOTH_VERSIONS), 0);
    CHECK(t, tls_peer_version() == NULL);
    CHECK_EQ_I64(t, tls_peer_send(&one, 1), TLS_PEER_ERR_NOT_STARTED);
    CHECK_EQ_I64(t, tls_peer_alert((tls_peer_alert_t) 99), TLS_PEER_ERR_BAD_ARGUMENT);
    CHECK_EQ_I64(t, tls_peer_step(), 0);
    tls_peer_stop();
    tls_peer_stop();
}

static void t_peer_garbage_ends_the_session(ctest_t *t)
{
    int ret;
    CHECK_EQ_I64(t, tls_peer_start(TLS_PEER_EC_VALID, TLS_PEER_BOTH_VERSIONS), 0);
    memset(g_buf, 0x41, 64);
    CHECK_EQ_I64(t, tls_peer_put(g_buf, 64), 0);
    ret = tls_peer_step();
    CHECK(t, ret < 0);
    CHECK_EQ_I64(t, tls_peer_error(), ret);
    CHECK_EQ_I64(t, tls_peer_step(), ret);
    tls_peer_stop();
}

static void t_entropy_is_live(ctest_t *t)
{
    unsigned char a[32];
    unsigned char b[32];
    static mbedtls_entropy_context entropy;
    mbedtls_entropy_init(&entropy);
    CHECK_EQ_I64(t, mbedtls_entropy_func(&entropy, a, sizeof a), 0);
    CHECK_EQ_I64(t, mbedtls_entropy_func(&entropy, b, sizeof b), 0);
    CHECK(t, memcmp(a, b, sizeof a) != 0);
    mbedtls_entropy_free(&entropy);
}

static void t_pinned_version(ctest_t *t)
{
    char version[18];
    mbedtls_version_get_string(version);
    CHECK_EQ_STR(t, version, "3.6.7");
}

CTEST_SUITE("tls", { "tls13_ecdsa", t_tls13_ecdsa }, { "tls13_rsa", t_tls13_rsa },
            { "tls12_peer_only", t_tls12_peer_only }, { "tls12_client_only", t_tls12_client_only },
            { "chain_with_intermediate", t_chain_with_intermediate }, { "expired", t_expired },
            { "not_yet_valid", t_not_yet_valid }, { "wrong_host", t_wrong_host }, { "unknown_ca", t_unknown_ca },
            { "other_ca_trusted_instead", t_other_ca_trusted_instead },
            { "wrong_name_asked_for", t_wrong_name_asked_for }, { "time_windows", t_time_windows },
            { "clock_not_injected", t_clock_not_injected }, { "client_close_notify", t_client_close_notify },
            { "peer_close_notify_is_eof", t_peer_close_notify_is_eof },
            { "truncation_is_detected", t_truncation_is_detected },
            { "truncation_inside_a_record", t_truncation_inside_a_record },
            { "peer_fatal_alert", t_peer_fatal_alert },
            { "peer_alert_during_the_handshake", t_peer_alert_during_the_handshake },
            { "bulk_data_both_ways", t_bulk_data_both_ways }, { "peer_state_machine", t_peer_state_machine },
            { "peer_garbage_ends_the_session", t_peer_garbage_ends_the_session },
            { "entropy_is_live", t_entropy_is_live }, { "pinned_version", t_pinned_version })
