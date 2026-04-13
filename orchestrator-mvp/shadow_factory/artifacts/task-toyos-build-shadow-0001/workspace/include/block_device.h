#ifndef BLOCK_DEVICE_H
#define BLOCK_DEVICE_H

#include <stddef.h>
#include <stdint.h>

#define BLOCK_DEVICE_BLOCK_SIZE 512u
#define BLOCK_DEVICE_BLOCK_COUNT 128u

void block_device_initialize(void);
size_t block_device_capacity(void);
int block_device_write(size_t block_index, const uint8_t* data, size_t length);
int block_device_read(size_t block_index, uint8_t* out, size_t length);

#endif
