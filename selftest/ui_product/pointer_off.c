/* The toy's build WITHOUT a pointer entry (U05c): `uim_pointer` (model.c) returns false and the probe injects its taps
 * at the app's pointer indev. */
#include "ui/model/model.h"

bool uim_pointer_supported(void)
{
    return false;
}
