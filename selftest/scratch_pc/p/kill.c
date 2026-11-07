#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#define PING(pid) kill((pid), 0)
int ping(int pid) { return PING(pid); }
