/* The gate's LVGL 9.6.0 configuration (T107). Forced on every user through -DLV_CONF_PATH=<gate_lv_conf.h>.
 * docs/third-party.md explains each decision. Anything not set here takes the library's default from
 * lv_conf_internal.h, so every option that must be off for the gate is set to 0 explicitly. */
#ifndef LV_CONF_H
#define LV_CONF_H

/* ---- memory: LVGL's own TLSF allocator over a pool the PRODUCT hands in -------------------------------
 * No static pool in the library and no libc malloc. LV_MEM_SIZE is the size of the one pool and the
 * ceiling of the allocator (512 KiB). The product calls lvgl_gate_set_pool(mem, LV_MEM_SIZE) (lvgl_gate.h)
 * once, before lv_init(). The builtin allocator then asks for it through LV_MEM_POOL_ALLOC. */
#define LV_USE_STDLIB_MALLOC  LV_STDLIB_BUILTIN
#define LV_USE_STDLIB_STRING  LV_STDLIB_BUILTIN
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_BUILTIN
#define LV_MEM_SIZE           (512 * 1024)
#define LV_MEM_ADR            0
#define LV_MEM_POOL_INCLUDE   "lvgl_gate.h"
#define LV_MEM_POOL_ALLOC(size) lvgl_gate_pool_take(size)

/* ---- no OS: LVGL lives on the product's single UI thread ---------------------------------------------- */
#define LV_USE_OS LV_OS_NONE

/* ---- software renderer only, 32 bit colour ------------------------------------------------------------ */
#define LV_COLOR_FORMAT_DEFAULT LV_COLOR_FORMAT_XRGB8888
#define LV_USE_DRAW_SW 1
#define LV_DRAW_SW_SUPPORT_RGB565             0
#define LV_DRAW_SW_SUPPORT_RGB565_SWAPPED     0
#define LV_DRAW_SW_SUPPORT_RGB565A8           0
#define LV_DRAW_SW_SUPPORT_RGB888             0
#define LV_DRAW_SW_SUPPORT_XRGB8888           1
#define LV_DRAW_SW_SUPPORT_ARGB8888           1
#define LV_DRAW_SW_SUPPORT_ARGB8888_PREMULTIPLIED 0
#define LV_DRAW_SW_SUPPORT_L8                 0
#define LV_DRAW_SW_SUPPORT_AL88               0
#define LV_DRAW_SW_SUPPORT_A8                 1
#define LV_DRAW_SW_SUPPORT_I1                 0
#define LV_DRAW_SW_DRAW_UNIT_CNT 1
#define LV_USE_DRAW_SW_ASM LV_DRAW_SW_ASM_NONE
#define LV_USE_NATIVE_HELIUM_ASM 0
#define LV_USE_DRAW_ARM2D_SYNC 0
#define LV_USE_VECTOR_GRAPHIC 0
#define LV_USE_THORVG 0
#define LV_USE_SNAPSHOT 0
#define LV_USE_MATRIX 0
#define LV_USE_FLOAT 0
/* every other draw unit and GPU backend */
#define LV_USE_DRAW_VG_LITE 0
#define LV_USE_VG_LITE_DRIVER 0
#define LV_USE_VG_LITE_THORVG 0
#define LV_USE_DRAW_DAVE2D 0
#define LV_USE_DRAW_PXP 0
#define LV_USE_PXP 0
#define LV_USE_PPA 0
#define LV_USE_DRAW_DMA2D 0
#define LV_USE_DRAW_EVE 0
#define LV_USE_SIFLI_EPIC 0
#define LV_USE_G2D 0
#define LV_USE_NEMA_GFX 0
#define LV_USE_DRAW_NANOVG 0
#define LV_USE_NANOVG 0
#define LV_USE_DRAW_OPENGLES 0
#define LV_USE_OPENGLES 0
#define LV_USE_DRAW_SDL 0
#define LV_USE_3DTEXTURE 0
#define LV_USE_GLTF 0

/* ---- logging off, assertions that stop the program ---------------------------------------------------- */
#define LV_USE_LOG 0
#define LV_USE_SYSMON 0
#define LV_USE_PERF_MONITOR 0
#define LV_USE_MEM_MONITOR 0
#define LV_USE_PROFILER 0
/* An assertion that fails traps (SIGILL on x86-64: the process dies, nothing spins). Out-of-memory in an
 * internal allocation and a NULL argument are asserted; lv_malloc() itself still returns NULL. */
#define LV_ASSERT_HANDLER __builtin_trap();
#define LV_USE_ASSERT 1
#define LV_USE_ASSERT_MALLOC 1
#define LV_USE_ASSERT_NULL 1
#define LV_USE_ASSERT_STYLE 0
#define LV_USE_ASSERT_MEM_INTEGRITY 0
#define LV_USE_ASSERT_OBJ 0

/* ---- no file system, no file-based decoders, nothing that opens a file -------------------------------- */
#define LV_USE_FS_STDIO 0
#define LV_USE_FS_POSIX 0
#define LV_USE_FS_WIN32 0
#define LV_USE_FS_FATFS 0
#define LV_USE_FS_LITTLEFS 0
#define LV_USE_FS_ARDUINO_ESP_LITTLEFS 0
#define LV_USE_FS_ARDUINO_SD 0
#define LV_USE_FS_UEFI 0
#define LV_USE_FS_FROGFS 0
#define LV_USE_FS_MEMFS 0
#define LV_USE_LODEPNG 0
#define LV_USE_LIBPNG 0
#define LV_USE_BMP 0
#define LV_USE_TJPGD 0
#define LV_USE_LIBJPEG_TURBO 0
#define LV_USE_LIBWEBP 0
#define LV_USE_GIF 0
#define LV_USE_SVG 0
#define LV_USE_FFMPEG 0
#define LV_USE_GSTREAMER 0
#define LV_USE_BARCODE 0
#define LV_USE_QRCODE 0
#define LV_USE_LOTTIE 0
#define LV_USE_RLOTTIE 0
#define LV_USE_RLE 0
#define LV_USE_LZ4 0
#define LV_USE_TEST_SCREENSHOT_COMPARE 0

/* ---- test display and test input (src/debugging/test), for product tests ------------------------------ */
#define LV_USE_TEST 1

/* ---- core features the kiosk does not use ------------------------------------------------------------- */
#define LV_USE_OBSERVER 0
#define LV_USE_OBJ_PROPERTY 0
#define LV_USE_OBJ_ID 0
#define LV_USE_OBJ_NAME 0
#define LV_USE_EXT_DATA 0
#define LV_USE_TRANSLATION 0
#define LV_USE_COLOR_FILTER 0
#define LV_USE_BIDI 0
#define LV_USE_ARABIC_PERSIAN_CHARS 0
#define LV_USE_GRIDNAV 0
#define LV_USE_GESTURE_RECOGNITION 0
#define LV_USE_FONT_MANAGER 0
#define LV_USE_IMGFONT 0
#define LV_USE_FREETYPE 0
#define LV_USE_FONT_COMPRESSED 0

/* ---- layouts and theme -------------------------------------------------------------------------------- */
#define LV_USE_FLEX 1
#define LV_USE_GRID 1
#define LV_USE_THEME_DEFAULT 1
#define LV_USE_THEME_SIMPLE 0
#define LV_USE_THEME_MONO 0

/* ---- fonts: the built-in Montserrat 14 (Latin, digits, symbols) is the fallback; Bulgarian text comes
 * from a TTF the product ships and loads from memory with lv_tiny_ttf_create_data() ----------------------- */
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_DEFAULT &lv_font_montserrat_14
#define LV_USE_TINY_TTF 1
#define LV_TINY_TTF_FILE_SUPPORT 0
#define LV_TINY_TTF_CACHE_GLYPH_CNT 128
#define LV_TINY_TTF_CACHE_KERNING_CNT 256
/* stb_truetype rounds with floor()/ceil(), which clang turns into libm calls (floorf/ceilf) that products do
 * not link. Integer versions instead; glyph coordinates are small, and x is a pure expression there. */
#define STBTT_ifloor(x) ((int)(x) - (((x) < (float)(int)(x)) ? 1 : 0))
#define STBTT_iceil(x)  ((int)(x) + (((x) > (float)(int)(x)) ? 1 : 0))

/* ---- widgets: obj (core), label, button, image ------------------------------------------------------- */
#define LV_USE_LABEL 1
#define LV_USE_BUTTON 1
#define LV_USE_IMAGE 1
#define LV_USE_ANIMIMG 0
#define LV_USE_ARC 0
#define LV_USE_ARCLABEL 0
#define LV_USE_BAR 0
#define LV_USE_BUTTONMATRIX 0
#define LV_USE_CALENDAR 0
#define LV_USE_CANVAS 0
#define LV_USE_CHART 0
#define LV_USE_CHECKBOX 0
#define LV_USE_DROPDOWN 0
#define LV_USE_IMAGEBUTTON 0
#define LV_USE_IME_PINYIN 0
#define LV_USE_KEYBOARD 0
#define LV_USE_LED 0
#define LV_USE_LINE 0
#define LV_USE_LIST 0
#define LV_USE_MENU 0
#define LV_USE_MSGBOX 0
#define LV_USE_ROLLER 0
#define LV_USE_SCALE 0
#define LV_USE_SLIDER 0
#define LV_USE_SPAN 0
#define LV_USE_SPINBOX 0
#define LV_USE_SPINNER 0
#define LV_USE_SWITCH 0
#define LV_USE_TEXTAREA 0
#define LV_USE_TABLE 0
#define LV_USE_TABVIEW 0
#define LV_USE_TILEVIEW 0
#define LV_USE_WIN 0

/* ---- display and input drivers: the product supplies its own ------------------------------------------ */
#define LV_USE_LINUX_DRM 0
#define LV_USE_LINUX_FBDEV 0
#define LV_USE_EVDEV 0
#define LV_USE_LIBINPUT 0
#define LV_USE_SDL 0
#define LV_USE_X11 0
#define LV_USE_WAYLAND 0
#define LV_USE_WINDOWS 0
#define LV_USE_UEFI 0
#define LV_USE_QNX 0
#define LV_USE_NUTTX 0
#define LV_USE_GLFW 0
#define LV_USE_FT81X 0
#define LV_USE_LOVYAN_GFX 0
#define LV_USE_TFT_ESPI 0
#define LV_USE_GENERIC_MIPI 0
#define LV_USE_ST7735 0
#define LV_USE_ST7789 0
#define LV_USE_ST7796 0
#define LV_USE_ILI9341 0
#define LV_USE_NV3007 0
#define LV_USE_NXP_ELCDIF 0
#define LV_USE_RENESAS_GLCDC 0
#define LV_USE_ST_LTDC 0

#endif /* LV_CONF_H */
