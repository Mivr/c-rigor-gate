/* Ordinary product code that calls a model symbol. The symbols gate must flag it (docs/ui-model.md, "Confinement"). */
#include "ui/model/model.h"

bool misuse_peek(uint64_t now_ms)
{
    return uim_open(uim_instance(), now_ms, 1u);
}
