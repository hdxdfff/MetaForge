#include "paging.h"

#define PAGE_PRESENT 0x001u
#define PAGE_WRITABLE 0x002u
#define PAGE_USER 0x004u
#define PAGE_SIZE_BYTES 4096u
#define PAGE_ENTRIES 1024u
#define IDENTITY_TABLES 2u
#define TOYOS_PAGING_STAGE1_CANARY 0xC0DEFACEu

static uint32_t page_directory[PAGE_ENTRIES] __attribute__((aligned(PAGE_SIZE_BYTES)));
static uint32_t page_tables[IDENTITY_TABLES][PAGE_ENTRIES] __attribute__((aligned(PAGE_SIZE_BYTES)));
static uint8_t g_paging_enabled = 0;
static volatile uint32_t g_stage1_canary = 0;

void paging_initialize(void) {
    for (size_t dir = 0; dir < PAGE_ENTRIES; ++dir) {
        page_directory[dir] = 0;
    }
    for (size_t table = 0; table < IDENTITY_TABLES; ++table) {
        for (size_t entry = 0; entry < PAGE_ENTRIES; ++entry) {
            uint32_t physical = (uint32_t)((table * PAGE_ENTRIES + entry) * PAGE_SIZE_BYTES);
            page_tables[table][entry] = physical | PAGE_PRESENT | PAGE_WRITABLE | PAGE_USER;
        }
        page_directory[table] = ((uint32_t)(uintptr_t)page_tables[table]) | PAGE_PRESENT | PAGE_WRITABLE | PAGE_USER;
    }
    __asm__ __volatile__("mov %0, %%cr3" : : "r"((uint32_t)(uintptr_t)page_directory) : "memory");
    uint32_t cr0;
    __asm__ __volatile__("mov %%cr0, %0" : "=r"(cr0));
    cr0 |= 0x80000000u;
    __asm__ __volatile__("mov %0, %%cr0" : : "r"(cr0) : "memory");
    g_paging_enabled = 1;
}

int paging_stage1_smoke_enable(void) {
    g_stage1_canary = TOYOS_PAGING_STAGE1_CANARY;
    paging_initialize();
    if (!g_paging_enabled) {
        return 0;
    }
    if (g_stage1_canary != TOYOS_PAGING_STAGE1_CANARY) {
        return 0;
    }
    if (paging_directory_address() == 0) {
        return 0;
    }
    return 1;
}

int paging_user_accessible_range(uintptr_t address, size_t size, uint8_t write_access) {
    uintptr_t mapped_limit;
    uintptr_t end_address;
    (void)write_access;

    if (size == 0) {
        return 0;
    }
    if (!g_paging_enabled) {
        return 1;
    }

    mapped_limit = (uintptr_t)(paging_mapped_megabytes() * 1024u * 1024u);
    if (address >= mapped_limit) {
        return 0;
    }
    end_address = address + size - 1u;
    if (end_address < address) {
        return 0;
    }
    if (end_address >= mapped_limit) {
        return 0;
    }
    return 1;
}

uint8_t paging_enabled(void) {
    return g_paging_enabled;
}

size_t paging_mapped_megabytes(void) {
    return (IDENTITY_TABLES * PAGE_ENTRIES * PAGE_SIZE_BYTES) / (1024u * 1024u);
}

uintptr_t paging_directory_address(void) {
    return (uintptr_t)page_directory;
}
