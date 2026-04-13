#ifndef IDT_H
#define IDT_H

#include <stdint.h>

typedef struct {
    uint32_t edi;
    uint32_t esi;
    uint32_t ebp;
    uint32_t esp;
    uint32_t ebx;
    uint32_t edx;
    uint32_t ecx;
    uint32_t eax;
} register_frame_t;

typedef void (*interrupt_handler_t)(uint32_t vector, register_frame_t* frame);

void idt_initialize(void);
void register_interrupt_handler(uint8_t vector, interrupt_handler_t handler);
void isr_dispatch_handler(uint32_t vector, register_frame_t* frame);

#endif
