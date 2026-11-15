/* Ordinary product code that defines a model symbol. The symbols gate must flag it (docs/ui-model.md, "Confinement"). */
#include "ui/model/model.h"

uint64_t uim_next_due(const uim_t *m)
{
    (void)m;
    return UIM_NO_DEADLINE;
}
