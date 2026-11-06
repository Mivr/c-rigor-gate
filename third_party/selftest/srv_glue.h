/* Self-test server (T009): an in-memory TLS server on a renamed private copy of the library
 * (every exported symbol is prefixed srv_). Plain C types only. One server at a time. */
#ifndef SRV_GLUE_H
#define SRV_GLUE_H

#include <stddef.h>

/* PEM of the test CA, NUL-terminated (length strlen + 1 for the library). */
const char *srv_ca_pem(void);

/* Start a server. use_rsa: RSA certificate instead of ECDSA. tls12_only: refuse TLS 1.3.
 * Returns 0 or a negative library error. */
int srv_start(int use_rsa, int tls12_only);
void srv_stop(void);

/* Bytes from the client into the server; bytes from the server for the client. */
int srv_put(const unsigned char *data, size_t len);
size_t srv_take(unsigned char *out, size_t cap);

/* Advance the server: handshake, then echo whatever application data arrived. Returns 0 when
 * there is nothing more to do now, a negative library error when it failed. */
int srv_step(void);
int srv_established(void);
const char *srv_version(void);

#endif
