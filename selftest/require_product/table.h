#ifndef TABLE_H
#define TABLE_H

enum { TABLE_CAP = 4 };

/* The value at `index`; `index` must be below TABLE_CAP (a guard stops the process otherwise). */
int table_get(unsigned index);

#endif
