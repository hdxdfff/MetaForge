#include "vfs.h"

#include "block_device.h"
#include "io.h"
#include "spinlock.h"

#define TINYFS_MAGIC_0 'T'
#define TINYFS_MAGIC_1 'F'
#define TINYFS_MAGIC_2 'S'
#define TINYFS_MAGIC_3 '1'
#define TINYFS_SUPERBLOCK_INDEX 0u
#define TINYFS_DIRECTORY_BLOCK_INDEX 1u
#define TINYFS_FIRST_DATA_BLOCK 2u

typedef struct {
    uint8_t magic[4];
    uint16_t max_files;
    uint16_t first_data_block;
    uint16_t mounted;
    uint8_t reserved[BLOCK_DEVICE_BLOCK_SIZE - 10];
} tinyfs_superblock_t;

typedef struct {
    char name[TINYFS_NAME_CAPACITY];
    uint16_t size;
    uint16_t block_index;
    uint8_t used;
    uint8_t reserved[3];
} tinyfs_disk_entry_t;

static ramfs_file_t ramfs_files[RAMFS_MAX_FILES];
static tinyfs_file_t tinyfs_files[TINYFS_MAX_FILES];
static uint8_t tinyfs_mounted = 0;
static spinlock_t vfs_lock;

static void vfs_debug_write(const char* text) {
    if (!text) {
        return;
    }
    while (*text) {
        outb(0xE9, (uint8_t)*text++);
    }
}

static void vfs_debug_writeln(const char* text) {
    vfs_debug_write(text);
    vfs_debug_write("\r\n");
}

static size_t str_length(const char* text) {
    size_t length = 0;
    while (text[length] != '\0') {
        ++length;
    }
    return length;
}

static int str_equal(const char* left, const char* right) {
    size_t index = 0;
    while (left[index] != '\0' && right[index] != '\0') {
        if (left[index] != right[index]) {
            return 0;
        }
        ++index;
    }
    return left[index] == right[index];
}

static size_t str_copy_limit(char* dest, const char* src, size_t limit) {
    size_t i = 0;
    if (limit == 0) {
        return 0;
    }
    while (src[i] != '\0' && i + 1 < limit) {
        dest[i] = src[i];
        ++i;
    }
    dest[i] = '\0';
    return i;
}

static void str_copy(char* dest, const char* src, size_t limit) {
    (void)str_copy_limit(dest, src, limit);
}

static void mem_zero(uint8_t* dest, size_t size) {
    for (size_t i = 0; i < size; ++i) {
        dest[i] = 0;
    }
}

static ramfs_file_t* ramfs_find_mut_locked(const char* name) {
    for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
        if (ramfs_files[i].used && str_equal(ramfs_files[i].name, name)) {
            return &ramfs_files[i];
        }
    }
    return 0;
}

static tinyfs_file_t* tinyfs_find_mut_locked(const char* name) {
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        if (tinyfs_files[i].used && str_equal(tinyfs_files[i].name, name)) {
            return &tinyfs_files[i];
        }
    }
    return 0;
}

static int tinyfs_flush_directory_locked(void) {
    uint8_t buffer[BLOCK_DEVICE_BLOCK_SIZE];
    tinyfs_disk_entry_t* entries = (tinyfs_disk_entry_t*)buffer;

    mem_zero(buffer, sizeof(buffer));
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        str_copy(entries[i].name, tinyfs_files[i].name, sizeof(entries[i].name));
        entries[i].size = tinyfs_files[i].size;
        entries[i].block_index = tinyfs_files[i].block_index;
        entries[i].used = tinyfs_files[i].used;
    }
    return block_device_write(TINYFS_DIRECTORY_BLOCK_INDEX, buffer, sizeof(buffer));
}

static int tinyfs_mount_locked(void) {
    uint8_t buffer[BLOCK_DEVICE_BLOCK_SIZE];
    tinyfs_superblock_t* superblock = (tinyfs_superblock_t*)buffer;
    tinyfs_disk_entry_t* entries;

    vfs_debug_writeln("VFS: mount read super");
    if (block_device_read(TINYFS_SUPERBLOCK_INDEX, buffer, sizeof(buffer)) != 0) {
        return -1;
    }
    if (superblock->magic[0] != TINYFS_MAGIC_0 || superblock->magic[1] != TINYFS_MAGIC_1 || superblock->magic[2] != TINYFS_MAGIC_2 || superblock->magic[3] != TINYFS_MAGIC_3) {
        return -1;
    }
    vfs_debug_writeln("VFS: mount read dir");
    if (block_device_read(TINYFS_DIRECTORY_BLOCK_INDEX, buffer, sizeof(buffer)) != 0) {
        return -1;
    }

    entries = (tinyfs_disk_entry_t*)buffer;
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        str_copy(tinyfs_files[i].name, entries[i].name, sizeof(tinyfs_files[i].name));
        tinyfs_files[i].size = entries[i].size;
        tinyfs_files[i].block_index = entries[i].block_index;
        tinyfs_files[i].used = entries[i].used;
    }
    tinyfs_mounted = 1;
    vfs_debug_writeln("VFS: mount done");
    return 0;
}

static int tinyfs_create_locked(const char* name) {
    if (!tinyfs_mounted && tinyfs_mount_locked() != 0) {
        return -1;
    }
    if (tinyfs_find_mut_locked(name)) {
        return 0;
    }
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        if (!tinyfs_files[i].used) {
            tinyfs_files[i].used = 1;
            tinyfs_files[i].size = 0;
            tinyfs_files[i].block_index = (uint16_t)(TINYFS_FIRST_DATA_BLOCK + i);
            str_copy(tinyfs_files[i].name, name, sizeof(tinyfs_files[i].name));
            return tinyfs_flush_directory_locked();
        }
    }
    return -1;
}

void vfs_initialize(void) {
    spinlock_initialize(&vfs_lock);
    for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
        ramfs_files[i].name[0] = '\0';
        ramfs_files[i].size = 0;
        ramfs_files[i].used = 0;
    }
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        tinyfs_files[i].name[0] = '\0';
        tinyfs_files[i].size = 0;
        tinyfs_files[i].block_index = (uint16_t)(TINYFS_FIRST_DATA_BLOCK + i);
        tinyfs_files[i].used = 0;
    }
    tinyfs_mounted = 0;
}

const ramfs_file_t* ramfs_find(const char* name) {
    const ramfs_file_t* result;
    spinlock_acquire(&vfs_lock);
    result = ramfs_find_mut_locked(name);
    spinlock_release(&vfs_lock);
    return result;
}

int ramfs_create(const char* name) {
    int status = -1;
    spinlock_acquire(&vfs_lock);
    if (ramfs_find_mut_locked(name)) {
        status = 0;
    } else {
        for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
            if (!ramfs_files[i].used) {
                ramfs_files[i].used = 1;
                ramfs_files[i].size = 0;
                str_copy(ramfs_files[i].name, name, sizeof(ramfs_files[i].name));
                status = 0;
                break;
            }
        }
    }
    spinlock_release(&vfs_lock);
    return status;
}

int ramfs_write_text(const char* name, const char* text) {
    int status = -1;
    spinlock_acquire(&vfs_lock);
    ramfs_file_t* file = ramfs_find_mut_locked(name);
    if (!file) {
        for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
            if (!ramfs_files[i].used) {
                ramfs_files[i].used = 1;
                ramfs_files[i].size = 0;
                str_copy(ramfs_files[i].name, name, sizeof(ramfs_files[i].name));
                file = &ramfs_files[i];
                break;
            }
        }
    }
    if (file) {
        size_t length = str_length(text);
        if (length >= RAMFS_FILE_CAPACITY) {
            length = RAMFS_FILE_CAPACITY - 1;
        }
        for (size_t i = 0; i < length; ++i) {
            file->data[i] = (uint8_t)text[i];
        }
        file->data[length] = 0;
        file->size = length;
        status = 0;
    }
    spinlock_release(&vfs_lock);
    return status;
}

int ramfs_read_text(const char* name, char* out, size_t capacity) {
    int status = -1;
    ramfs_file_t* file;
    if (!out || capacity == 0) {
        return -1;
    }

    spinlock_acquire(&vfs_lock);
    file = ramfs_find_mut_locked(name);
    if (file) {
        str_copy_limit(out, (const char*)file->data, capacity);
        status = 0;
    } else {
        out[0] = '\0';
    }
    spinlock_release(&vfs_lock);
    return status;
}

size_t ramfs_file_count(void) {
    size_t count = 0;
    spinlock_acquire(&vfs_lock);
    for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
        if (ramfs_files[i].used) {
            ++count;
        }
    }
    spinlock_release(&vfs_lock);
    return count;
}

const ramfs_file_t* ramfs_get_at(size_t index) {
    const ramfs_file_t* result = 0;
    size_t current = 0;
    spinlock_acquire(&vfs_lock);
    for (size_t i = 0; i < RAMFS_MAX_FILES; ++i) {
        if (!ramfs_files[i].used) {
            continue;
        }
        if (current == index) {
            result = &ramfs_files[i];
            break;
        }
        ++current;
    }
    spinlock_release(&vfs_lock);
    return result;
}

int tinyfs_format(void) {
    int status;
    uint8_t buffer[BLOCK_DEVICE_BLOCK_SIZE];
    tinyfs_superblock_t* superblock = (tinyfs_superblock_t*)buffer;

    vfs_debug_writeln("VFS: format start");
    vfs_debug_writeln("VFS: acquire lock");
    spinlock_acquire(&vfs_lock);
    vfs_debug_writeln("VFS: lock acquired");
    mem_zero(buffer, sizeof(buffer));
    superblock->magic[0] = TINYFS_MAGIC_0;
    superblock->magic[1] = TINYFS_MAGIC_1;
    superblock->magic[2] = TINYFS_MAGIC_2;
    superblock->magic[3] = TINYFS_MAGIC_3;
    superblock->max_files = TINYFS_MAX_FILES;
    superblock->first_data_block = TINYFS_FIRST_DATA_BLOCK;
    superblock->mounted = 1;
    vfs_debug_writeln("VFS: write superblock");
    status = block_device_write(TINYFS_SUPERBLOCK_INDEX, buffer, sizeof(buffer));
    if (status == 0) {
        vfs_debug_writeln("VFS: superblock written");
        for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
            tinyfs_files[i].name[0] = '\0';
            tinyfs_files[i].size = 0;
            tinyfs_files[i].block_index = (uint16_t)(TINYFS_FIRST_DATA_BLOCK + i);
            tinyfs_files[i].used = 0;
            mem_zero(buffer, sizeof(buffer));
            if (block_device_write(tinyfs_files[i].block_index, buffer, sizeof(buffer)) != 0) {
                status = -1;
                break;
            }
        }
    }
    tinyfs_mounted = status == 0 ? 1 : 0;
    if (status == 0) {
        vfs_debug_writeln("VFS: data blocks cleared");
        status = tinyfs_flush_directory_locked();
    }
    spinlock_release(&vfs_lock);
    if (status == 0) {
        vfs_debug_writeln("VFS: format done");
    }
    return status;
}
int tinyfs_mount(void) {
    int status;
    spinlock_acquire(&vfs_lock);
    status = tinyfs_mount_locked();
    spinlock_release(&vfs_lock);
    return status;
}

int tinyfs_create(const char* name) {
    int status;
    spinlock_acquire(&vfs_lock);
    status = tinyfs_create_locked(name);
    spinlock_release(&vfs_lock);
    return status;
}

int tinyfs_write_text(const char* name, const char* text) {
    int status = -1;
    uint8_t buffer[BLOCK_DEVICE_BLOCK_SIZE];
    tinyfs_file_t* file;
    size_t length;

    vfs_debug_writeln("VFS: write start");
    spinlock_acquire(&vfs_lock);
    file = tinyfs_find_mut_locked(name);
    if (!file) {
        if (tinyfs_create_locked(name) == 0) {
            file = tinyfs_find_mut_locked(name);
        }
    }
    if (file) {
        length = str_length(text);
        if (length >= TINYFS_FILE_CAPACITY) {
            length = TINYFS_FILE_CAPACITY - 1;
        }
        mem_zero(buffer, sizeof(buffer));
        for (size_t i = 0; i < length; ++i) {
            buffer[i] = (uint8_t)text[i];
        }
        buffer[length] = 0;
        file->size = (uint16_t)length;
        if (block_device_write(file->block_index, buffer, sizeof(buffer)) == 0) {
            status = tinyfs_flush_directory_locked();
        }
    }
    spinlock_release(&vfs_lock);
    if (status == 0) {
        vfs_debug_writeln("VFS: write done");
    }
    return status;
}

int tinyfs_read_text(const char* name, char* out, size_t capacity) {
    int status = -1;
    uint8_t buffer[BLOCK_DEVICE_BLOCK_SIZE];
    tinyfs_file_t* file;
    if (!out || capacity == 0) {
        return -1;
    }

    spinlock_acquire(&vfs_lock);
    file = tinyfs_find_mut_locked(name);
    if (!file && !tinyfs_mounted) {
        if (tinyfs_mount_locked() == 0) {
            file = tinyfs_find_mut_locked(name);
        }
    }
    if (file && block_device_read(file->block_index, buffer, sizeof(buffer)) == 0) {
        str_copy_limit(out, (const char*)buffer, capacity);
        status = 0;
    } else {
        out[0] = '\0';
    }
    spinlock_release(&vfs_lock);
    return status;
}

size_t tinyfs_file_count(void) {
    size_t count = 0;
    spinlock_acquire(&vfs_lock);
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        if (tinyfs_files[i].used) {
            ++count;
        }
    }
    spinlock_release(&vfs_lock);
    return count;
}

const tinyfs_file_t* tinyfs_get_at(size_t index) {
    const tinyfs_file_t* result = 0;
    size_t current = 0;
    spinlock_acquire(&vfs_lock);
    for (size_t i = 0; i < TINYFS_MAX_FILES; ++i) {
        if (!tinyfs_files[i].used) {
            continue;
        }
        if (current == index) {
            result = &tinyfs_files[i];
            break;
        }
        ++current;
    }
    spinlock_release(&vfs_lock);
    return result;
}

