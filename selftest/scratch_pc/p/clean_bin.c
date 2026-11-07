#include <stdio.h>
#include "clean.h"
int main(void) { return printf("%d\n", clean_len()) > 0 ? 0 : 1; }
