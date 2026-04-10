#ifndef VFS_H
#define VFS_H

#include <stddef.h>
#include <stdint.h>

#define RAMFS_MAX_FILES 16
#define RAMFS_FILE_CAPACITY 256
#define TINYFS_MAX_FILES 8
#define TINYFS_NAME_CAPACITY 24
#define TINYFS_FILE_CAPACITY 128

typedef struct {
    char name[32];
    uint8_t data[RAMFS_FILE_CAPACITY];
    size_t size;
    uint8_t used;
} ramfs_file_t;

typedef struct {
    char name[TINYFS_NAME_CAPACITY];
    uint16_t size;
    uint16_t block_index;
    uint8_t used;
} tinyfs_file_t;

void vfs_initialize(void);

int ramfs_create(const char* name);
int ramfs_write_text(const char* name, const char* text);
int ramfs_read_text(const char* name, char* out, size_t capacity);
const ramfs_file_t* ramfs_find(const char* name);
size_t ramfs_file_count(void);
const ramfs_file_t* ramfs_get_at(size_t index);

int tinyfs_format(void);
int tinyfs_mount(void);
int tinyfs_create(const char* name);
int tinyfs_write_text(const char* name, const char* text);
int tinyfs_read_text(const char* name, char* out, size_t capacity);
size_t tinyfs_file_count(void);
const tinyfs_file_t* tinyfs_get_at(size_t index);

#endif
