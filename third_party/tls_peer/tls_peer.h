/* TLS test peer: a real TLS server (mbedTLS 3.6.7, server enabled) that lives in memory, for the tests of
 * a TLS client adapter. Gate-owned (`gate//third_party/tls_peer:tls_peer`); only a `c_test` may name it.
 * Plain C types only: this header includes no mbedTLS header, so it can be used next to the client
 * library the product really links.
 *
 * WHAT IT IS
 *   No sockets, no clock, no files, no threads. You move bytes: whatever the client under test writes goes
 *   in with tls_peer_put(), whatever the peer wants to send comes out of tls_peer_take(). tls_peer_step()
 *   lets the peer process what it was given. One peer at a time (global state; tls_peer_start() resets).
 *
 * THE LOOP (the client side is yours)
 *     tls_peer_start(TLS_PEER_EC_VALID, TLS_PEER_BOTH_VERSIONS);
 *     for (round = 0; round < 64 && !done; round++) {
 *         done = <one client handshake step, which wrote into your out buffer>;
 *         tls_peer_put(out, out_len);  out_len = 0;
 *         tls_peer_step();
 *         in_len += tls_peer_take(in + in_len, sizeof in - in_len);
 *     }
 *   Return values: 0 is success or "nothing more to do now"; a negative value is a mbedTLS error code
 *   (the library's, e.g. -0x7780). Calls on a peer that was not started return TLS_PEER_ERR_NOT_STARTED.
 *
 * THE TEST PKI (throwaway; never trust it outside tests)
 *   All server identities answer to TLS_PEER_HOST ("tls.test.invalid") except where noted. The client
 *   trusts tls_peer_ca_pem() (the root CA) to verify them. Validity and the time to inject:
 *
 *     identity                   certificate                         expect, with TLS_PEER_TIME_VALID
 *     TLS_PEER_EC_VALID          ECDSA P-256, root CA                verifies (verify flags 0)
 *     TLS_PEER_RSA_VALID         RSA-2048, root CA                   verifies
 *     TLS_PEER_EXPIRED           ECDSA, root CA, ended 2021-01-01    MBEDTLS_X509_BADCERT_EXPIRED
 *     TLS_PEER_NOT_YET_VALID     ECDSA, root CA, from 2100-01-01     MBEDTLS_X509_BADCERT_FUTURE
 *     TLS_PEER_WRONG_HOST        ECDSA, root CA, host wrong-host...  MBEDTLS_X509_BADCERT_CN_MISMATCH
 *     TLS_PEER_UNKNOWN_CA        ECDSA, signed by a hidden CA        MBEDTLS_X509_BADCERT_NOT_TRUSTED
 *     TLS_PEER_CHAIN             ECDSA, intermediate, root CA        verifies (the peer sends the intermediate)
 *
 *   A second, unrelated CA is tls_peer_other_ca_pem(): a client that trusts only that one refuses every
 *   identity above with MBEDTLS_X509_BADCERT_NOT_TRUSTED. The CA certificates are valid 2020-01-01 to
 *   2126-01-01; the server certificates 2026-01-01 to 2126-01-01 unless the table says otherwise.
 *
 *   Time: the client library has no clock (its time is 0 until the product injects one with
 *   mbedtls_platform_set_time(), so every certificate is "not yet valid"). Inject one of:
 *     TLS_PEER_TIME_VALID           2027-01-01  every valid identity is in its window; expired and
 *                                               not-yet-valid are not
 *     TLS_PEER_TIME_EXPIRED_WINDOW  2020-07-01  inside the window of TLS_PEER_EXPIRED only (and the CAs)
 *     TLS_PEER_TIME_FUTURE_WINDOW   2110-01-01  inside the window of TLS_PEER_NOT_YET_VALID, and of the
 *                                               valid identities too
 *
 * LIMITS
 *   Buffers: 32 KiB each way, 4 KiB of received application data. Versions: TLS 1.3 and 1.2, ECDHE with
 *   AES-GCM or ChaCha20-Poly1305. No client certificates, no session tickets, no renegotiation, no
 *   compression, SNI and ALPN are not evaluated. The peer is not sanitizer-instrumented in the `san` mode
 *   (two instrumented copies of one library in one process are an ASan odr-violation); the client
 *   library is.
 *
 * TRUNCATION
 *   tls_peer_stop() sends nothing. To test a connection that ends without close_notify, call
 *   tls_peer_stop() (or just stop calling tls_peer_take()) and make your transport report end of file;
 *   the client library then reports an end of file (mbedtls_ssl_read returns 0 or MBEDTLS_ERR_SSL_CONN_EOF), whereas
 *   a clean close is MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY; an adapter must not map both to "end of stream". To cut inside a record,
 *   give tls_peer_take() a capacity smaller than what is pending.
 *
 * THESE KEYS ARE THROWAWAY TEST KEYS. They are public test data and secure nothing.
 *
 * Reserved: every symbol of this library starts with tls_peer_ or srv_; a product may define neither.
 */
#ifndef TLS_PEER_H
#define TLS_PEER_H

#include <stddef.h>

#define TLS_PEER_HOST "tls.test.invalid"
#define TLS_PEER_HOST_WRONG "wrong-host.test.invalid"

#define TLS_PEER_TIME_VALID 1798761600L
#define TLS_PEER_TIME_EXPIRED_WINDOW 1593561600L
#define TLS_PEER_TIME_FUTURE_WINDOW 4417977600L

#define TLS_PEER_ERR_NOT_STARTED (-1)
#define TLS_PEER_ERR_BAD_ARGUMENT (-2)
#define TLS_PEER_ERR_FULL (-3)

typedef enum {
    TLS_PEER_EC_VALID = 0,
    TLS_PEER_RSA_VALID,
    TLS_PEER_EXPIRED,
    TLS_PEER_NOT_YET_VALID,
    TLS_PEER_WRONG_HOST,
    TLS_PEER_UNKNOWN_CA,
    TLS_PEER_CHAIN,
    TLS_PEER_IDENTITY_COUNT
} tls_peer_identity_t;

typedef enum {
    TLS_PEER_BOTH_VERSIONS = 0, /* offers TLS 1.3 and 1.2; against a client that offers both, 1.3 is chosen */
    TLS_PEER_TLS12_ONLY         /* refuses TLS 1.3 */
} tls_peer_versions_t;

/* Fatal alerts the peer can send (RFC 8446 numbers). */
typedef enum {
    TLS_PEER_ALERT_UNEXPECTED_MESSAGE = 10,
    TLS_PEER_ALERT_BAD_RECORD_MAC = 20,
    TLS_PEER_ALERT_HANDSHAKE_FAILURE = 40,
    TLS_PEER_ALERT_DECODE_ERROR = 50,
    TLS_PEER_ALERT_PROTOCOL_VERSION = 70,
    TLS_PEER_ALERT_INTERNAL_ERROR = 80
} tls_peer_alert_t;

/* PEM text, NUL-terminated; pass strlen + 1 as the length to mbedtls_x509_crt_parse(). */
const char *tls_peer_ca_pem(void);       /* the root CA: the client's trust anchor */
const char *tls_peer_other_ca_pem(void); /* an unrelated CA that signed nothing the peer serves */

/* Start (or restart) the peer with a server identity. Returns 0 or a negative mbedTLS error. */
int tls_peer_start(tls_peer_identity_t identity, tls_peer_versions_t versions);
/* Free everything. Sends nothing (no close_notify). Safe to call twice or when not started. */
void tls_peer_stop(void);

/* Bytes from the client into the peer: 0, TLS_PEER_ERR_FULL when 32 KiB are already pending. */
int tls_peer_put(const unsigned char *data, size_t len);
/* Bytes from the peer for the client; returns how many were copied (at most cap). */
size_t tls_peer_take(unsigned char *out, size_t cap);

/* Let the peer work: the handshake until it is complete, then read the client's application data into
 * the receive queue. Returns 0 (done for now, including "client sent close_notify"), or the negative
 * mbedTLS error that ended the session; the same value is returned by every later call and by
 * tls_peer_error(). */
int tls_peer_step(void);

int tls_peer_established(void);           /* 1 once the handshake completed */
const char *tls_peer_version(void);       /* "TLSv1.3" or "TLSv1.2" once established, else NULL */
int tls_peer_error(void);                 /* the error that ended the session, 0 if none */
int tls_peer_client_closed(void);         /* 1 once the client's close_notify was read */
size_t tls_peer_received(unsigned char *out, size_t cap); /* pop application data the client sent */

/* Peer to client. Each needs an established session (alerts: any time after tls_peer_start). */
int tls_peer_send(const unsigned char *data, size_t len); /* application data; 0 or a negative error */
int tls_peer_close_notify(void);                          /* a clean close */
int tls_peer_alert(tls_peer_alert_t alert);               /* a fatal alert; the session is over */

#endif
