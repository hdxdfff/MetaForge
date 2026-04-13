#ifndef MEMORY_H
#define MEMORY_H

#include <stddef.h>
#include <stdint.h>

void memory_initialize(void);
void* kmalloc(size_t size);
void* page_alloc(void);
void page_free(void* page);
size_t memory_heap_used(void);
size_t memory_pages_used(void);
size_t memory_pages_total(void);
uintptr_t memory_page_base(void* page);

#endif
