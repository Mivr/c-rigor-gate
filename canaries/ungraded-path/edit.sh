set -eu
mkdir -p http
printf 'load("@gate//rules:c.bzl", "c_library")\n\nc_library(name = "http", srcs = ["http.c"], headers = ["http.h"], visibility = ["PUBLIC"])\n' > http/BUCK
printf '#ifndef HTTP_H\n#define HTTP_H\nint http_status(void);\n#endif\n' > http/http.h
printf '#include "http.h"\n\nint http_status(void) { return 200; }\n' > http/http.c
