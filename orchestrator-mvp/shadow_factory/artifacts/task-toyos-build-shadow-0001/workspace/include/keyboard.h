#ifndef KEYBOARD_H
#define KEYBOARD_H

#include <stddef.h>
#include <stdint.h>

void keyboard_initialize(void);
size_t keyboard_pending(void);
int keyboard_read_char(void);

#endif
