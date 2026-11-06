/* Throwaway product module of the TLS peer self-test: a TLS client on the gate-owned mbedTLS library
 * with a byte-buffer transport, the shape of a `tls_stream` adapter. Product rules apply to it. */
#ifndef TLS_CLIENT_H
#define TLS_CLIENT_H

#include <stddef.h>
#include <stdint.h>

#define TLS_CLIENT_AGAIN (-1)
#define TLS_CLIENT_CLOSED (-2)    /* the peer sent close_notify: a clean end */
#define TLS_CLIENT_TRUNCATED (-3) /* the transport ended without close_notify: an attack or a fault */

/* Start a client that trusts `ca_pem` (NUL-terminated PEM) and expects `host`. 0 or an mbedTLS error. */
int tls_client_start(const char *ca_pem, const char *host, int tls12_only);
void tls_client_stop(void);

/* Transport: bytes for the peer, bytes from the peer, and "the connection ended" (no close_notify). */
size_t tls_client_outgoing(unsigned char *out, size_t cap);
void tls_client_incoming(const unsigned char *data, size_t len);
void tls_client_eof(void);

/* mbedtls_ssl_handshake(): 0 done, MBEDTLS_ERR_SSL_WANT_* to go on, anything else failed. */
int tls_client_handshake(void);
int tls_client_write(const unsigned char *data, size_t len);
/* >0 bytes read, TLS_CLIENT_AGAIN nothing yet, TLS_CLIENT_CLOSED, TLS_CLIENT_TRUNCATED, else the mbedTLS error. */
int tls_client_read(unsigned char *out, size_t cap);
int tls_client_close(void);

uint32_t tls_client_verify_flags(void);
const char *tls_client_version(void);

#endif
