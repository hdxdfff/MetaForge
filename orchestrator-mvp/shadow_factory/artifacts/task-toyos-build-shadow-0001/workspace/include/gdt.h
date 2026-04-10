#ifndef GDT_H
#define GDT_H

#include <stdint.h>

void gdt_initialize(void);
void gdt_set_kernel_stack(uint32_t stack_top);
uint8_t gdt_user_mode_ready(void);
uint8_t gdt_tss_ready(void);
uint16_t gdt_kernel_code_selector(void);
uint16_t gdt_kernel_data_selector(void);
uint16_t gdt_user_code_selector(void);
uint16_t gdt_user_data_selector(void);
uint16_t gdt_tss_selector(void);
uint32_t gdt_kernel_stack_top(void);

#endif
