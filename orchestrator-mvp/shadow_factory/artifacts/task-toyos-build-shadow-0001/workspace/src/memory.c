#include "memory.h"

#define HEAP_SIZE_BYTES (64 * 1024)
#define PAGE_SIZE 4096u
#define PAGE_COUNT 128u

static uint8_t kernel_heap[HEAP_SIZE_BYTES];
static size_t heap_offset = 0;
static uint8_t page_bitmap[PAGE_COUNT];
static uint8_t page_storage[PAGE_COUNT][PAGE_SIZE];
static size_t used_pages = 0;

void memory_initialize(void) {
    heap_offset = 0;
    used_pages = 0;
    for (size_t i = 0; i < PAGE_COUNT; ++i) {
        page_bitmap[i] = 0;
    }
}

void* kmalloc(size_t size) {
    if (size == 0) {
        return 0;
    }
    size = (size + 7u) & ~7u;
    if (heap_offset + size > HEAP_SIZE_BYTES) {
        return 0;
    }
    void* block = &kernel_heap[heap_offset];
    heap_offset += size;
    return block;
}

void* page_alloc(void) {
    for (size_t i = 0; i < PAGE_COUNT; ++i) {
        if (page_bitmap[i] == 0) {
            page_bitmap[i] = 1;
            ++used_pages;
            return page_storage[i];
        }
    }
    return 0;
}

void page_free(void* page) {
    if (!page) {
        return;
    }
    for (size_t i = 0; i < PAGE_COUNT; ++i) {
        if ((void*)page_storage[i] == page && page_bitmap[i] != 0) {
            page_bitmap[i] = 0;
            --used_pages;
            return;
        }
    }
}

size_t memory_heap_used(void) {
    return heap_offset;
}

size_t memory_pages_used(void) {
    return used_pages;
}

size_t memory_pages_total(void) {
    return PAGE_COUNT;
}

uintptr_t memory_page_base(void* page) {
    if (!page) {
        return 0;
    }
    for (size_t i = 0; i < PAGE_COUNT; ++i) {
        if ((void*)page_storage[i] == page) {
            return (uintptr_t)page_storage[i];
        }
    }
    return 0;
}
