#ifndef LIT_H
#define LIT_H
typedef enum { LIT_OK = 0, LIT_ERR_LOW = 1, LIT_ERR_HIGH = 2 } lit_status;
int lit_get(const int *p);
lit_status lit_check(int v);
const char *lit_name(void);
char lit_letter(void);
#endif
