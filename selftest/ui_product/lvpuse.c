/* Ordinary product code that calls a symbol of the gate's lvprobe. The symbols gate must flag it whatever its policy
 * allows (docs/ui-model.md, "Confinement"): only the gate's probe library may call lvprobe. */
#include <stddef.h>
#include <stdint.h>

uint16_t lvprobe_count(const void *p);
uint16_t lvpuse_peek(void);

uint16_t lvpuse_peek(void)
{
    return lvprobe_count(NULL);
}
