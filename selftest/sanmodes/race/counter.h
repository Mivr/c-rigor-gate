#ifndef COUNTER_H
#define COUNTER_H

/* Two threads add to one counter; returns 1 when it ends above zero (always), -1 when a thread call fails. */
int counter_run(void);

#endif
