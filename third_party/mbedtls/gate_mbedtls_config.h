/* Gate-owned Mbed TLS 3.6 configuration (T009). Client only: TLS 1.2 and TLS 1.3, X.509 parsing,
 * PEM, ECDHE with ECDSA or RSA certificates, AES-GCM and ChaCha20-Poly1305, SHA-2, the PSA core.
 *
 * Everything not listed here is OFF. In particular there is no server, no SSLv3/TLS 1.0/1.1, no
 * DTLS, no renegotiation, no session tickets, no PSK, no static ECDH, no DHE, no SHA-1, no MD5, no
 * CBC/ECB/CTR/CCM, no 3DES/DES/ARIA/Camellia, no assembly, no sockets (the product supplies the
 * BIO), no file I/O (a CA bundle is passed as a buffer), no debug output, no threading, no timing
 * module, no self tests. Clock: PLATFORM_TIME_ALT, so the library reads no ambient clock for
 * certificate validity; until the product calls mbedtls_platform_set_time() the time is 0 and every
 * certificate is "not yet valid" (fail closed). Entropy: getrandom(2) only, through the gate's
 * mbedtls_hardware_poll() in gate_platform.c (the stock source falls back to /dev/urandom). A change here is an owner-approved gate change (docs/third-party.md). */
#ifndef GATE_MBEDTLS_CONFIG_H
#define GATE_MBEDTLS_CONFIG_H

/* ---- platform ---- */
#define MBEDTLS_PLATFORM_C
#define MBEDTLS_PLATFORM_MEMORY          /* the product may hand in an arena allocator */
#define MBEDTLS_HAVE_TIME
#define MBEDTLS_HAVE_TIME_DATE
#define MBEDTLS_PLATFORM_TIME_ALT
#define MBEDTLS_PLATFORM_STD_TIME mbedtls_gate_time_unset   /* gate_platform.c: always 0 */
#if !defined(__ASSEMBLER__)
long mbedtls_gate_time_unset(long *timer);
#endif
#define MBEDTLS_ERROR_C
#define MBEDTLS_VERSION_C

/* ---- entropy and randomness ---- */
#define MBEDTLS_ENTROPY_C
#define MBEDTLS_NO_PLATFORM_ENTROPY
#define MBEDTLS_ENTROPY_HARDWARE_ALT     /* mbedtls_hardware_poll() in gate_platform.c: getrandom only */
#define MBEDTLS_CTR_DRBG_C

/* ---- hashes, MACs, KDF ---- */
#define MBEDTLS_SHA224_C
#define MBEDTLS_SHA256_C
#define MBEDTLS_SHA384_C
#define MBEDTLS_SHA512_C
#define MBEDTLS_MD_C
#define MBEDTLS_HKDF_C

/* ---- ciphers ---- */
#define MBEDTLS_AES_C
#define MBEDTLS_GCM_C
#define MBEDTLS_CHACHA20_C
#define MBEDTLS_POLY1305_C
#define MBEDTLS_CHACHAPOLY_C
#define MBEDTLS_CIPHER_C

/* ---- public key ---- */
#define MBEDTLS_BIGNUM_C
#define MBEDTLS_OID_C
#define MBEDTLS_ASN1_PARSE_C
#define MBEDTLS_ASN1_WRITE_C
#define MBEDTLS_RSA_C
#define MBEDTLS_PKCS1_V15
#define MBEDTLS_PKCS1_V21
#define MBEDTLS_ECP_C
#define MBEDTLS_ECDH_C
#define MBEDTLS_ECDSA_C
#define MBEDTLS_ECP_DP_SECP256R1_ENABLED
#define MBEDTLS_ECP_DP_SECP384R1_ENABLED
#define MBEDTLS_ECP_DP_CURVE25519_ENABLED
#define MBEDTLS_ECP_NIST_OPTIM
#define MBEDTLS_PK_C
#define MBEDTLS_PK_PARSE_C
#define MBEDTLS_PK_WRITE_C

/* ---- PSA crypto core (TLS 1.3 needs it) ---- */
#define MBEDTLS_PSA_CRYPTO_C

/* ---- X.509 and PEM: parsing and verification only ---- */
#define MBEDTLS_X509_USE_C
#define MBEDTLS_X509_RSASSA_PSS_SUPPORT   /* TLS 1.3 signs with RSA-PSS */
#define MBEDTLS_X509_CRT_PARSE_C
#define MBEDTLS_PEM_PARSE_C
#define MBEDTLS_BASE64_C

/* ---- TLS client ---- */
#define MBEDTLS_SSL_TLS_C
#define MBEDTLS_SSL_CLI_C
#define MBEDTLS_SSL_PROTO_TLS1_2
#define MBEDTLS_SSL_PROTO_TLS1_3
#define MBEDTLS_SSL_TLS1_3_COMPATIBILITY_MODE
#define MBEDTLS_SSL_TLS1_3_KEY_EXCHANGE_MODE_EPHEMERAL_ENABLED
#define MBEDTLS_KEY_EXCHANGE_ECDHE_RSA_ENABLED
#define MBEDTLS_KEY_EXCHANGE_ECDHE_ECDSA_ENABLED
#define MBEDTLS_SSL_EXTENDED_MASTER_SECRET
#define MBEDTLS_SSL_ENCRYPT_THEN_MAC
#define MBEDTLS_SSL_SERVER_NAME_INDICATION
#define MBEDTLS_SSL_ALPN
#define MBEDTLS_SSL_KEEP_PEER_CERTIFICATE

#endif /* GATE_MBEDTLS_CONFIG_H */
