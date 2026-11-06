/* TLS test peer (T009, T012): the gate's client configuration plus a TLS server, so the real client
 * library can be tested against a real server in one process. Only the peer's private copy of the
 * library is built with it; the library a product links (//third_party/mbedtls:mbedtls) has no server. */
#ifndef SRV_CONFIG_H
#define SRV_CONFIG_H

#include "gate_mbedtls_config.h"

#define MBEDTLS_SSL_SRV_C

#endif
