/* Self-test only (T009): the gate's client configuration plus a TLS server, so the real client
 * library can be tested against a real server in one process. Never used by a product. */
#ifndef SRV_CONFIG_H
#define SRV_CONFIG_H

#include "gate_mbedtls_config.h"

#define MBEDTLS_SSL_SRV_C

#endif
