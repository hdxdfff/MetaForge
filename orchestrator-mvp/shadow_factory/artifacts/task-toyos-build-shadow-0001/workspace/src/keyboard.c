#include "keyboard.h"

#include "idt.h"
#include "io.h"

#define KEYBOARD_BUFFER_SIZE 64

static char key_buffer[KEYBOARD_BUFFER_SIZE];
static size_t key_head = 0;
static size_t key_tail = 0;

static char scancode_to_ascii(uint8_t scancode) {
    static const char map[128] = {
        0,  27, '1', '2', '3', '4', '5', '6',
        '7', '8', '9', '0', '-', '=', '\b', '\t',
        'q', 'w', 'e', 'r', 't', 'y', 'u', 'i',
        'o', 'p', '[', ']', '\n', 0,   'a', 's',
        'd', 'f', 'g', 'h', 'j', 'k', 'l', ';',
        '\'', '`', 0,  '\\', 'z', 'x', 'c', 'v',
        'b', 'n', 'm', ',', '.', '/', 0,   '*',
        0,  ' ', 0
    };
    if (scancode >= sizeof(map)) {
        return 0;
    }
    return map[scancode];
}

static void keyboard_push(char ch) {
    size_t next = (key_tail + 1) % KEYBOARD_BUFFER_SIZE;
    if (next == key_head) {
        return;
    }
    key_buffer[key_tail] = ch;
    key_tail = next;
}

static void keyboard_interrupt_handler(uint32_t vector, register_frame_t* frame) {
    uint8_t scancode = inb(0x60);
    char ch;
    (void)vector;
    (void)frame;

    if ((scancode & 0x80) != 0) {
        return;
    }
    ch = scancode_to_ascii(scancode);
    if (ch != 0) {
        keyboard_push(ch);
    }
}

void keyboard_initialize(void) {
    key_head = 0;
    key_tail = 0;
    register_interrupt_handler(0x21, keyboard_interrupt_handler);
}

size_t keyboard_pending(void) {
    if (key_tail >= key_head) {
        return key_tail - key_head;
    }
    return KEYBOARD_BUFFER_SIZE - key_head + key_tail;
}

int keyboard_read_char(void) {
    char ch;
    if (key_head == key_tail) {
        return -1;
    }
    ch = key_buffer[key_head];
    key_head = (key_head + 1) % KEYBOARD_BUFFER_SIZE;
    return (int)ch;
}
