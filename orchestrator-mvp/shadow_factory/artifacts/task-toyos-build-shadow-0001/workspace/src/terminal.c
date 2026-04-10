#include "terminal.h"

static volatile uint16_t* const VGA_BUFFER = (uint16_t*)0xB8000;
static const size_t VGA_WIDTH = 80;
static const size_t VGA_HEIGHT = 25;

static size_t terminal_row = 0;
static size_t terminal_column = 0;
static uint8_t terminal_color = 0x0F;

static uint16_t vga_entry(unsigned char ch, uint8_t color) {
    return (uint16_t)ch | ((uint16_t)color << 8);
}

static void terminal_put_entry_at(char ch, uint8_t color, size_t x, size_t y) {
    const size_t index = y * VGA_WIDTH + x;
    VGA_BUFFER[index] = vga_entry((unsigned char)ch, color);
}

static void terminal_newline(void) {
    terminal_column = 0;
    if (++terminal_row < VGA_HEIGHT) {
        return;
    }

    for (size_t y = 1; y < VGA_HEIGHT; ++y) {
        for (size_t x = 0; x < VGA_WIDTH; ++x) {
            VGA_BUFFER[(y - 1) * VGA_WIDTH + x] = VGA_BUFFER[y * VGA_WIDTH + x];
        }
    }
    for (size_t x = 0; x < VGA_WIDTH; ++x) {
        terminal_put_entry_at(' ', terminal_color, x, VGA_HEIGHT - 1);
    }
    terminal_row = VGA_HEIGHT - 1;
}

void terminal_initialize(void) {
    terminal_row = 0;
    terminal_column = 0;
    terminal_color = 0x0F;
    for (size_t y = 0; y < VGA_HEIGHT; ++y) {
        for (size_t x = 0; x < VGA_WIDTH; ++x) {
            terminal_put_entry_at(' ', terminal_color, x, y);
        }
    }
}

void terminal_set_color(uint8_t color) {
    terminal_color = color;
}

void terminal_write(const char* data) {
    for (size_t i = 0; data[i] != '\0'; ++i) {
        if (data[i] == '\n') {
            terminal_newline();
            continue;
        }
        terminal_put_entry_at(data[i], terminal_color, terminal_column, terminal_row);
        if (++terminal_column == VGA_WIDTH) {
            terminal_newline();
        }
    }
}

void terminal_writeln(const char* data) {
    terminal_write(data);
    terminal_newline();
}

void terminal_write_hex(uint32_t value) {
    const char* digits = "0123456789ABCDEF";
    terminal_write("0x");
    for (int shift = 28; shift >= 0; shift -= 4) {
        terminal_put_entry_at(digits[(value >> shift) & 0xF], terminal_color, terminal_column, terminal_row);
        if (++terminal_column == VGA_WIDTH) {
            terminal_newline();
        }
    }
}
