#ifndef XLINK_H
#define XLINK_H

/* 1 if XOpenDisplay(":99999") returned NULL (no such display; needs no X server), else 0. */
int xlink_open_fails(void);
/* XStringToKeysym("a") == XK_a (a pure table lookup inside libX11), 1 or 0. */
int xlink_keysym_a(void);

#endif
