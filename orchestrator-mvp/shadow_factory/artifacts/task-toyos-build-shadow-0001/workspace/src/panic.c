#include "panic.h"

#include "io.h"
#include "terminal.h"

static void panic_debug_write(const char* text) {
    if (!text) {
        return;
    }
    while (*text) {
        outb(0xE9, (uint8_t)*text++);
    }
}

void panic(const char* message) {
    __asm__ __volatile__("cli");
    panic_debug_write("PANIC: ");
    panic_debug_write(message ? message : "unknown panic");
    panic_debug_write("\r\n");
    terminal_set_color(0x4F);
    terminal_writeln("");
    terminal_writeln("*** KERNEL PANIC ***");
    terminal_set_color(0x0F);
    terminal_writeln(message ? message : "unknown panic");
    for (;;) {
        __asm__ __volatile__("hlt");
    }
}
