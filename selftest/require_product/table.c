#include "table.h"
#include "rt/require.h"

static const int g_values[TABLE_CAP] = {10, 20, 30, 40};

int table_get(unsigned index) {
    rigor_require(index < TABLE_CAP);
    return g_values[index];
}
