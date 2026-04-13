#ifndef SYSCALL_H
#define SYSCALL_H

#include <stdint.h>

enum {
    TOYOS_SYSCALL_STATUS_OK = 0u,
    TOYOS_SYSCALL_STATUS_INVALID = 0xFFFFFFFFu,
    TOYOS_SYSCALL_STATUS_FAULT = 0xFFFFFFFEu,
};

enum {
    SYSCALL_WRITE_LOG = 1,
    SYSCALL_YIELD = 2,
    SYSCALL_EXIT = 3,
    SYSCALL_QUERY_PID = 4,
    SYSCALL_CONSOLE_WRITE = 5,
    SYSCALL_READ_KEY = 6,
    SYSCALL_QUERY_TICKS = 7,
    SYSCALL_QUERY_HEAP_USED = 8,
    SYSCALL_QUERY_PAGES_USED = 9,
    SYSCALL_RAMFS_COUNT = 10,
    SYSCALL_TINYFS_COUNT = 11,
    SYSCALL_RAMFS_NAME = 12,
    SYSCALL_TINYFS_NAME = 13,
    SYSCALL_RAMFS_READ = 14,
    SYSCALL_TINYFS_READ = 15,
};

void syscall_initialize(void);
uint32_t syscall_count(void);

static inline uint32_t syscall_invoke(uint32_t number, uint32_t arg0, uint32_t arg1, uint32_t arg2, uint32_t arg3) {
    uint32_t result;
    __asm__ __volatile__(
        "int $0x80"
        : "=a"(result)
        : "a"(number), "b"(arg0), "c"(arg1), "d"(arg2), "S"(arg3)
        : "memory"
    );
    return result;
}

#endif
