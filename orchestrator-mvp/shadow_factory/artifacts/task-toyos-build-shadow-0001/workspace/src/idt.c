#include "idt.h"
#include "io.h"
#include "terminal.h"

struct idt_entry {
    uint16_t offset_low;
    uint16_t selector;
    uint8_t zero;
    uint8_t type_attr;
    uint16_t offset_high;
} __attribute__((packed));

struct idt_ptr {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

extern void isr_default_stub(void);
extern void isr_irq0_stub(void);
extern void isr_irq1_stub(void);
extern void isr_syscall_stub(void);
extern void isr_err10_stub(void);
extern void isr_err11_stub(void);
extern void isr_err12_stub(void);
extern void isr_err13_stub(void);
extern void isr_err14_stub(void);

static struct idt_entry idt[256];
static struct idt_ptr idtp;
static interrupt_handler_t interrupt_handlers[256];

static void debug_vector(uint32_t vector) {
    const char* prefix = "INT: 0x";
    const char hex[] = "0123456789ABCDEF";
    while (*prefix) {
        outb(0xE9, (uint8_t)*prefix++);
    }
    outb(0xE9, (uint8_t)hex[(vector >> 4) & 0xF]);
    outb(0xE9, (uint8_t)hex[vector & 0xF]);
    outb(0xE9, (uint8_t)'\r');
    outb(0xE9, (uint8_t)'\n');
}

static void idt_set_gate(uint8_t index, uint32_t handler, uint16_t selector, uint8_t type_attr) {
    idt[index].offset_low = (uint16_t)(handler & 0xFFFF);
    idt[index].selector = selector;
    idt[index].zero = 0;
    idt[index].type_attr = type_attr;
    idt[index].offset_high = (uint16_t)((handler >> 16) & 0xFFFF);
}

static void pic_remap(void) {
    const uint8_t master_mask = inb(0x21);
    const uint8_t slave_mask = inb(0xA1);

    outb(0x20, 0x11);
    outb(0xA0, 0x11);
    outb(0x21, 0x20);
    outb(0xA1, 0x28);
    outb(0x21, 0x04);
    outb(0xA1, 0x02);
    outb(0x21, 0x01);
    outb(0xA1, 0x01);

    outb(0x21, master_mask);
    outb(0xA1, slave_mask);
}

void idt_initialize(void) {
    for (uint16_t i = 0; i < 256; ++i) {
        interrupt_handlers[i] = 0;
        idt_set_gate((uint8_t)i, (uint32_t)isr_default_stub, 0x08, 0x8E);
    }
    idt_set_gate(0x0A, (uint32_t)isr_err10_stub, 0x08, 0x8E);
    idt_set_gate(0x0B, (uint32_t)isr_err11_stub, 0x08, 0x8E);
    idt_set_gate(0x0C, (uint32_t)isr_err12_stub, 0x08, 0x8E);
    idt_set_gate(0x0D, (uint32_t)isr_err13_stub, 0x08, 0x8E);
    idt_set_gate(0x0E, (uint32_t)isr_err14_stub, 0x08, 0x8E);
    idt_set_gate(0x20, (uint32_t)isr_irq0_stub, 0x08, 0x8E);
    idt_set_gate(0x21, (uint32_t)isr_irq1_stub, 0x08, 0x8E);
    idt_set_gate(0x80, (uint32_t)isr_syscall_stub, 0x08, 0xEE);

    idtp.limit = (uint16_t)(sizeof(idt) - 1);
    idtp.base = (uint32_t)&idt;

    pic_remap();
    __asm__ __volatile__("lidt %0" : : "m"(idtp));
    __asm__ __volatile__("sti");
}

void register_interrupt_handler(uint8_t vector, interrupt_handler_t handler) {
    interrupt_handlers[vector] = handler;
}

void isr_dispatch_handler(uint32_t vector, register_frame_t* frame) {
    if (vector < 256 && interrupt_handlers[vector] != 0) {
        interrupt_handlers[vector](vector, frame);
    } else if (vector != 0x20 && vector != 0x21) {
        debug_vector(vector);
        terminal_set_color(0x4F);
        terminal_writeln("[interrupt] unhandled vector");
        terminal_set_color(0x0F);
    }

    if (vector >= 0x20 && vector < 0x30) {
        if (vector >= 0x28) {
            outb(0xA0, 0x20);
        }
        outb(0x20, 0x20);
    }
}
