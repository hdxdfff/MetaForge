#include "syscall.h"

#include "idt.h"
#include "io.h"
#include "keyboard.h"
#include "memory.h"
#include "paging.h"
#include "scheduler.h"
#include "terminal.h"
#include "timer.h"
#include "vfs.h"

static uint32_t g_syscall_count = 0;

typedef enum {
    SYSCALL_PTR_READ_ONLY = 1,
    SYSCALL_PTR_WRITE_ONLY = 2,
    SYSCALL_PTR_READ_WRITE = 3,
} syscall_pointer_access_t;

static uint32_t syscall_status_invalid(void) {
    return TOYOS_SYSCALL_STATUS_INVALID;
}

static uint32_t syscall_status_fault(void) {
    return TOYOS_SYSCALL_STATUS_FAULT;
}

static int syscall_validate_user_buffer(const void* pointer, size_t size, syscall_pointer_access_t access) {
    uint8_t write_access = access == SYSCALL_PTR_WRITE_ONLY || access == SYSCALL_PTR_READ_WRITE;
    if (!pointer) {
        return 0;
    }
    if (size == 0) {
        return 0;
    }
    if (!paging_user_accessible_range((uintptr_t)pointer, size, write_access)) {
        return 0;
    }
    return 1;
}

static int syscall_validate_user_string(const char* pointer, syscall_pointer_access_t access) {
    uint8_t write_access = access == SYSCALL_PTR_WRITE_ONLY || access == SYSCALL_PTR_READ_WRITE;
    size_t limit = 256u;
    size_t length = 0;

    if (!pointer) {
        return 0;
    }
    if (!paging_enabled()) {
        return syscall_validate_user_buffer(pointer, 1u, access);
    }
    while (length < limit) {
        if (!paging_user_accessible_range((uintptr_t)(pointer + length), 1u, write_access)) {
            return 0;
        }
        if (pointer[length] == '\0') {
            return 1;
        }
        ++length;
    }
    return 0;
}

static size_t syscall_str_copy(char* dest, const char* src, size_t limit) {
    size_t i = 0;
    if (!dest || limit == 0) {
        return 0;
    }
    while (src && src[i] != '\0' && i + 1 < limit) {
        dest[i] = src[i];
        ++i;
    }
    dest[i] = '\0';
    return i;
}

static void syscall_debug(const char* text) {
    if (!text) {
        return;
    }
    while (*text) {
        outb(0xE9, (uint8_t)*text++);
    }
    outb(0xE9, (uint8_t)'\r');
    outb(0xE9, (uint8_t)'\n');
}

static uint32_t syscall_handle(uint32_t number, uint32_t arg0, uint32_t arg1, uint32_t arg2, uint32_t arg3) {
    ++g_syscall_count;
    syscall_debug("SYSCALL: entered");

    switch (number) {
        case SYSCALL_WRITE_LOG:
            if (!syscall_validate_user_string((const char*)arg0, SYSCALL_PTR_READ_ONLY)) {
                return syscall_status_invalid();
            }
            syscall_debug((const char*)arg0);
            terminal_set_color(0x0B);
            terminal_write("[syscall] ");
            terminal_writeln((const char*)arg0);
            terminal_set_color(0x0F);
            if (ramfs_write_text("proc/syscall.last", (const char*)arg0) != 0) {
                return syscall_status_fault();
            }
            return TOYOS_SYSCALL_STATUS_OK;
        case SYSCALL_YIELD:
            syscall_debug("SYSCALL: yield requested");
            scheduler_yield_current();
            scheduler_request_ring0_return();
            return TOYOS_SYSCALL_STATUS_OK;
        case SYSCALL_EXIT:
            syscall_debug("SYSCALL: exit requested");
            scheduler_mark_current_exited((int32_t)arg0);
            scheduler_request_ring0_return();
            return TOYOS_SYSCALL_STATUS_OK;
        case SYSCALL_QUERY_PID:
            return scheduler_current_pid();
        case SYSCALL_CONSOLE_WRITE:
            if (!syscall_validate_user_string((const char*)arg0, SYSCALL_PTR_READ_ONLY)) {
                return syscall_status_invalid();
            }
            terminal_write((const char*)arg0);
            return TOYOS_SYSCALL_STATUS_OK;
        case SYSCALL_READ_KEY: {
            int ch = keyboard_read_char();
            return ch < 0 ? syscall_status_invalid() : (uint32_t)ch;
        }
        case SYSCALL_QUERY_TICKS:
            return timer_ticks();
        case SYSCALL_QUERY_HEAP_USED:
            return (uint32_t)memory_heap_used();
        case SYSCALL_QUERY_PAGES_USED:
            return (uint32_t)memory_pages_used();
        case SYSCALL_RAMFS_COUNT:
            return (uint32_t)ramfs_file_count();
        case SYSCALL_TINYFS_COUNT:
            return (uint32_t)tinyfs_file_count();
        case SYSCALL_RAMFS_NAME: {
            const ramfs_file_t* file;
            if (!syscall_validate_user_buffer((void*)arg1, (size_t)arg2, SYSCALL_PTR_WRITE_ONLY)) {
                return syscall_status_invalid();
            }
            file = ramfs_get_at((size_t)arg0);
            if (!file) {
                ((char*)arg1)[0] = '\0';
                return syscall_status_fault();
            }
            return (uint32_t)syscall_str_copy((char*)arg1, file->name, (size_t)arg2);
        }
        case SYSCALL_TINYFS_NAME: {
            const tinyfs_file_t* file;
            if (!syscall_validate_user_buffer((void*)arg1, (size_t)arg2, SYSCALL_PTR_WRITE_ONLY)) {
                return syscall_status_invalid();
            }
            file = tinyfs_get_at((size_t)arg0);
            if (!file) {
                ((char*)arg1)[0] = '\0';
                return syscall_status_fault();
            }
            return (uint32_t)syscall_str_copy((char*)arg1, file->name, (size_t)arg2);
        }
        case SYSCALL_RAMFS_READ:
            if (!syscall_validate_user_string((const char*)arg0, SYSCALL_PTR_READ_ONLY) ||
                !syscall_validate_user_buffer((void*)arg1, (size_t)arg2, SYSCALL_PTR_WRITE_ONLY)) {
                return syscall_status_invalid();
            }
            return ramfs_read_text((const char*)arg0, (char*)arg1, (size_t)arg2) == 0 ? TOYOS_SYSCALL_STATUS_OK : syscall_status_fault();
        case SYSCALL_TINYFS_READ:
            if (!syscall_validate_user_string((const char*)arg0, SYSCALL_PTR_READ_ONLY) ||
                !syscall_validate_user_buffer((void*)arg1, (size_t)arg2, SYSCALL_PTR_WRITE_ONLY)) {
                return syscall_status_invalid();
            }
            return tinyfs_read_text((const char*)arg0, (char*)arg1, (size_t)arg2) == 0 ? TOYOS_SYSCALL_STATUS_OK : syscall_status_fault();
        default:
            return syscall_status_invalid();
    }
}

static void syscall_interrupt_handler(uint32_t vector, register_frame_t* frame) {
    (void)vector;
    frame->eax = syscall_handle(frame->eax, frame->ebx, frame->ecx, frame->edx, frame->esi);
}

void syscall_initialize(void) {
    register_interrupt_handler(0x80, syscall_interrupt_handler);
}

uint32_t syscall_count(void) {
    return g_syscall_count;
}
