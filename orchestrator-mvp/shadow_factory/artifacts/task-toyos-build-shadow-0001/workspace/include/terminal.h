#ifndef TERMINAL_H
#define TERMINAL_H

#include <stddef.h>
#include <stdint.h>

void terminal_initialize(void);
void terminal_set_color(uint8_t color);
void terminal_write(const char* data);
void terminal_writeln(const char* data);
void terminal_write_hex(uint32_t value);

#endif
