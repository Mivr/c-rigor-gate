/* Test PKI for the third-party self-test (T009): a throwaway P-256 CA and two server identities for
 * tls.selftest.invalid. Public test data, valid until 2126; generated once with OpenSSL, never reused. */
#ifndef SRV_PKI_H
#define SRV_PKI_H

static const char srv_ca_pem_text[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBrjCCAVOgAwIBAgIUXN8lyUGBbWfYo+/VX3rKuATBIUYwCgYIKoZIzj0EAwIw\n"
    "IzEhMB8GA1UEAwwYYy1yaWdvci1nYXRlIHNlbGZ0ZXN0IENBMCAXDTI2MTEwNjEw\n"
    "MjkxMVoYDzIxMjYxMDEzMTAyOTExWjAjMSEwHwYDVQQDDBhjLXJpZ29yLWdhdGUg\n"
    "c2VsZnRlc3QgQ0EwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAATEQp9GeESEx+Cy\n"
    "95l0KI+6n8+jLpFDLFy4dZ9n6dYzwp4U3v+27mJSCILQ0+8RxIWX3u683QjiFUEx\n"
    "3+rvJyNjo2MwYTAdBgNVHQ4EFgQU1mbn/7gw5sJuPvM9Yd5Opzm6Xp4wHwYDVR0j\n"
    "BBgwFoAU1mbn/7gw5sJuPvM9Yd5Opzm6Xp4wDwYDVR0TAQH/BAUwAwEB/zAOBgNV\n"
    "HQ8BAf8EBAMCAQYwCgYIKoZIzj0EAwIDSQAwRgIhAIzXHXeZmWYlDFJ1EUj+V8IM\n"
    "OUBmb+YuKjJSHlXjzon5AiEA0u6gtKReyKANJVMU6vCn9w970M4RMUY8KpgB9Czv\n"
    "52Q=\n"
    "-----END CERTIFICATE-----\n";

static const char srv_ec_cert_pem[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIIB1zCCAX6gAwIBAgIUYMtlbl+ed7vxTVlsDqze7XEjIvYwCgYIKoZIzj0EAwIw\n"
    "IzEhMB8GA1UEAwwYYy1yaWdvci1nYXRlIHNlbGZ0ZXN0IENBMCAXDTI2MTEwNjEw\n"
    "MjkxMVoYDzIxMjYxMDEzMTAyOTExWjAfMR0wGwYDVQQDDBR0bHMuc2VsZnRlc3Qu\n"
    "aW52YWxpZDBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABC4q6y43nwiPR1oO+gkA\n"
    "YM+kah+zrnXq/K5FwmDwb0cDKl6B8NrT4YwMyNkBdY5AWjqD70khD3FcP6HBwRpX\n"
    "YlCjgZEwgY4wHwYDVR0RBBgwFoIUdGxzLnNlbGZ0ZXN0LmludmFsaWQwCQYDVR0T\n"
    "BAIwADALBgNVHQ8EBAMCB4AwEwYDVR0lBAwwCgYIKwYBBQUHAwEwHQYDVR0OBBYE\n"
    "FBiK0XuZB+TLZEzIhEEnnXGR7PolMB8GA1UdIwQYMBaAFNZm5/+4MObCbj7zPWHe\n"
    "Tqc5ul6eMAoGCCqGSM49BAMCA0cAMEQCIDhNpHbIe0bSahRUhtlE2w9OiyO9NNW+\n"
    "8WP6dYkLNkVPAiB3uOIqn+XcooBrRHmwRu9I10GG2o1qyGhlYTkDZTES1A==\n"
    "-----END CERTIFICATE-----\n";

static const char srv_ec_key_pem[] =
    "-----BEGIN PRIVATE KEY-----\n"
    "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgv8qkjPPvHfh7PjlE\n"
    "8aGphFyUXybeBo+7nii9GbT7pf6hRANCAAQuKusuN58Ij0daDvoJAGDPpGofs651\n"
    "6vyuRcJg8G9HAypegfDa0+GMDMjZAXWOQFo6g+9JIQ9xXD+hwcEaV2JQ\n"
    "-----END PRIVATE KEY-----\n";

static const char srv_rsa_cert_pem[] =
    "-----BEGIN CERTIFICATE-----\n"
    "MIICojCCAkmgAwIBAgIUYMtlbl+ed7vxTVlsDqze7XEjIvcwCgYIKoZIzj0EAwIw\n"
    "IzEhMB8GA1UEAwwYYy1yaWdvci1nYXRlIHNlbGZ0ZXN0IENBMCAXDTI2MTEwNjEw\n"
    "MjkxMVoYDzIxMjYxMDEzMTAyOTExWjAfMR0wGwYDVQQDDBR0bHMuc2VsZnRlc3Qu\n"
    "aW52YWxpZDCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALg/PRpg4roy\n"
    "ze2nSBO371sZnn2jgJl8oJLEszMQ9NW7I7tzy1vbwVA18X5U3s0SOBti4NSaMKyv\n"
    "7HkTHXBHEEsCIVm0JarCSsIDhJnYsV4dxtYsR5x3VxpR9Wg7UfuAaYrJr2O9cKDE\n"
    "zpNNHGRSzVHyZZZaoqo6owCR4cTXkoqMt62ZLhYVQxuOGJospUPJUSHM6xVywmI8\n"
    "4fIwGKUEjRsL9nl/RfhMuTNaCxtAv0QcQ4P2hv7MbFVmcHKjGKlVKB3rxYLRc/UD\n"
    "f5B+NbskJLEq1LAHt0qAKFOd1BbGyzhqcX02x2hIQ1in3garx4WDOzR4gpH6CXya\n"
    "9fEOJAdSKisCAwEAAaOBkTCBjjAfBgNVHREEGDAWghR0bHMuc2VsZnRlc3QuaW52\n"
    "YWxpZDAJBgNVHRMEAjAAMAsGA1UdDwQEAwIHgDATBgNVHSUEDDAKBggrBgEFBQcD\n"
    "ATAdBgNVHQ4EFgQUztonesoofS+lQi9D81UIuv8AImMwHwYDVR0jBBgwFoAU1mbn\n"
    "/7gw5sJuPvM9Yd5Opzm6Xp4wCgYIKoZIzj0EAwIDRwAwRAIgJuiVijLLZYTLQdWn\n"
    "YB3mCGAkx1nVBJNIF2EHq1iSccMCIGKxjziqNGQyq6LZU0n80aC/fEJxkOin2ZlB\n"
    "MT47DenP\n"
    "-----END CERTIFICATE-----\n";

static const char srv_rsa_key_pem[] =
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC4Pz0aYOK6Ms3t\n"
    "p0gTt+9bGZ59o4CZfKCSxLMzEPTVuyO7c8tb28FQNfF+VN7NEjgbYuDUmjCsr+x5\n"
    "Ex1wRxBLAiFZtCWqwkrCA4SZ2LFeHcbWLEecd1caUfVoO1H7gGmKya9jvXCgxM6T\n"
    "TRxkUs1R8mWWWqKqOqMAkeHE15KKjLetmS4WFUMbjhiaLKVDyVEhzOsVcsJiPOHy\n"
    "MBilBI0bC/Z5f0X4TLkzWgsbQL9EHEOD9ob+zGxVZnByoxipVSgd68WC0XP1A3+Q\n"
    "fjW7JCSxKtSwB7dKgChTndQWxss4anF9NsdoSENYp94Gq8eFgzs0eIKR+gl8mvXx\n"
    "DiQHUiorAgMBAAECggEACpfFxt0ru+IzrIZ+r0K9Qq+u4oqCpSoHcb8lJ5PBsWlG\n"
    "4FfQdcs+vbW6pcI+ywVRb3wLin2dvDGJg9tOL0hB26YkNIWWDGkkpiuDzw3CNZog\n"
    "3LhpmslrtLCVaBtpyiIzlZsLd+cKcVvPUQqEAUQxCy76zNGqL38bVwS/UuaRkmCN\n"
    "0KIjhq3YcqbKn2xY8YfJtN5v0YbkvhLj3WnZ0fyKapWrh9kjc2B4BoKhxtj/o6SR\n"
    "FbF/56/cWLM51Y1Ay/J/woLndaAnLNcdE/dpll5Tq2utJ+HMa/TwwUb2gMVPhiuI\n"
    "9aUYXcChZEfXkVf1y7KV55emVFgLr5Jt1bj5p7P1NQKBgQDzqyUPWnmIMH+bmBzL\n"
    "7NQ+O7kDDfWh1cjzicabSkJRe3DB117Mk1oZd+HNizWmh0QVZTjYNeMLgL5NNhZK\n"
    "OjpkfGwr2eQ9+D+AbRID44i7McIaNxJY0PSGjGpdnn5lE2G5g1ml2BdQ17zPP/lP\n"
    "/Hxy514/KjszQ2J8igunCzroZQKBgQDBkkG5IXE3f1vGRPCJX37bwLvTpiWelXyq\n"
    "gYr55amocC71c9VBWrwUZcUlMy5w7krg6cD26BKD244IJ/3U/YvFsFUsFlOX2hvm\n"
    "MrXXLmVLHhChEJvhxQZxmVhzsg2i0YkibfJGJZ+0Mx80/OgM5xEYjmJ8Ctz3m/QT\n"
    "gXc97A/3TwKBgCsmxdtgNGGP5SlS2NasTDHxNaR61mMgjwPCBG//yJrRd3h8gYdN\n"
    "GQmll1FlM80X61C2qkhv0pN46zqVN4FRqoGdHzLs1WS8D9LYffY+Vzp/Z1ZpJlCg\n"
    "QI2LVFLb/Jo9wnKt9jROfmKMsh0pwScPGaLnomMhQXakmk5fzAx7CqWZAoGAH6Id\n"
    "J3n1nJItl0sw2+JFQvhOOZpPT4kyZFLjOU902Ffs9KPHV/TSA6tV+mxQzJfEmNja\n"
    "df8a931ryp1ud94vd1EHujqz0n8MTCRBXzbvysTRBuFF+DFQikP7Fn0kiVUgygWZ\n"
    "sCj53mL0WJ5z9ZfVTWQHaCoGTlioHH/t0qq/OTUCgYEApp1Laf2ywkc6R7/sPhmL\n"
    "wjgFc+GqANdzp0P2DKuvCu+3tXIMQfq/jTAeFeJ3XWl4DIB4c21PSWSmsXqLgF02\n"
    "Ci1ZeDvI30zF569lrHQKI7VfPZAczj9ycMInvmMY+Hmjz2GGdfYZVYJn6w9OMxkV\n"
    "41qWFwlzLp0MeUvOIq0Foak=\n"
    "-----END PRIVATE KEY-----\n";

#endif
