#include "block_device.h"

#include "io.h"

static uint8_t ramdisk[BLOCK_DEVICE_BLOCK_COUNT][BLOCK_DEVICE_BLOCK_SIZE];

static void block_debug_char(char ch) {
    outb(0xE9, (uint8_t)ch);
}

void block_device_initialize(void) {
    for (size_t block = 0; block < BLOCK_DEVICE_BLOCK_COUNT; ++block) {
        for (size_t offset = 0; offset < BLOCK_DEVICE_BLOCK_SIZE; ++offset) {
            ramdisk[block][offset] = 0;
        }
    }
}

size_t block_device_capacity(void) {
    return BLOCK_DEVICE_BLOCK_COUNT;
}

int block_device_write(size_t block_index, const uint8_t* data, size_t length) {
    if (block_index >= BLOCK_DEVICE_BLOCK_COUNT || length > BLOCK_DEVICE_BLOCK_SIZE) {
        block_debug_char('!');
        return -1;
    }
    block_debug_char('W');
    for (size_t i = 0; i < length; ++i) {
        ramdisk[block_index][i] = data[i];
    }
    for (size_t i = length; i < BLOCK_DEVICE_BLOCK_SIZE; ++i) {
        ramdisk[block_index][i] = 0;
    }
    block_debug_char('w');
    return 0;
}

int block_device_read(size_t block_index, uint8_t* out, size_t length) {
    if (block_index >= BLOCK_DEVICE_BLOCK_COUNT || length > BLOCK_DEVICE_BLOCK_SIZE) {
        block_debug_char('?');
        return -1;
    }
    block_debug_char('R');
    for (size_t i = 0; i < length; ++i) {
        out[i] = ramdisk[block_index][i];
    }
    block_debug_char('r');
    return 0;
}
