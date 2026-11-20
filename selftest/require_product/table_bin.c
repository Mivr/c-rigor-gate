#include "rt/require.h"
#include "table.h"

int main(void) {
    int v = table_get(1);
    rigor_require(v == 20);
    return 0;
}
