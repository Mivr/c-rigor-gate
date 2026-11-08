#include "xlink.h"

#include <X11/XKBlib.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/keysym.h>
#include <stddef.h>

int xlink_open_fails(void) {
    Display *display = XOpenDisplay(":99999");
    if (display != NULL) {
        (void)XCloseDisplay(display);
        return 0;
    }
    return 1;
}

int xlink_keysym_a(void) { return XStringToKeysym("a") == (KeySym)XK_a ? 1 : 0; }
