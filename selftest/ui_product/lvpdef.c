/* Ordinary product code that defines a name with the gate's reserved `lvp_` prefix. The symbols gate must flag it
 * (docs/ui-model.md, "Confinement"). */
int lvp_mine(int x);

int lvp_mine(int x)
{
    return x + 1;
}
