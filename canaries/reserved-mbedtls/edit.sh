set -eu
printf '\nint mbedtls_ssl_read(int a);\nint mbedtls_ssl_read(int a) { return a; }\n' >> util/util.c
