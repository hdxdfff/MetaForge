#ifndef PAGING_H
#define PAGING_H

#include <stddef.h>
#include <stdint.h>

#ifndef TOYOS_EXPERIMENTAL_PAGING_STAGE1
#define TOYOS_EXPERIMENTAL_PAGING_STAGE1 0
#endif

void paging_initialize(void);
int paging_stage1_smoke_enable(void);
uint8_t paging_enabled(void);
size_t paging_mapped_megabytes(void);
int paging_user_accessible_range(uintptr_t address, size_t size, uint8_t write_access);
uintptr_t paging_directory_address(void);

#endif
