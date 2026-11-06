/* Gate-owned glue for the Mbed TLS configuration (T009): the two platform hooks the config selects.
 * Compiled into the library with its flags; everything here is Mbed TLS's reserved namespace. */
#include <errno.h>
#include <stddef.h>
#include <sys/random.h>

#include "mbedtls/entropy.h"

/* The library's clock until the product calls mbedtls_platform_set_time(): time 0, so every
 * certificate is "not yet valid". No ambient time() is ever read for certificate validity. */
long mbedtls_gate_time_unset(long *timer)
{
    if (timer != NULL) {
        *timer = 0;
    }
    return 0;
}

/* The only entropy source (MBEDTLS_NO_PLATFORM_ENTROPY + MBEDTLS_ENTROPY_HARDWARE_ALT): getrandom(2),
 * blocking until the kernel pool is ready, no fallback to /dev/urandom or anything else. */
int mbedtls_hardware_poll(void *data, unsigned char *output, size_t len, size_t *olen)
{
    size_t done = 0;

    (void) data;
    *olen = 0;
    while (done < len) {
        ssize_t got = getrandom(output + done, len - done, 0);
        if (got < 0) {
            if (errno == EINTR) {
                continue;
            }
            return MBEDTLS_ERR_ENTROPY_SOURCE_FAILED;
        }
        if (got == 0) {
            return MBEDTLS_ERR_ENTROPY_SOURCE_FAILED;
        }
        done += (size_t) got;
    }
    *olen = done;
    return 0;
}
