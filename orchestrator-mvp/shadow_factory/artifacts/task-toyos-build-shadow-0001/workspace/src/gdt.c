#include "gdt.h"

struct gdt_entry {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t base_middle;
    uint8_t access;
    uint8_t granularity;
    uint8_t base_high;
} __attribute__((packed));

struct gdt_ptr {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

typedef struct {
    uint32_t prev_tss;
    uint32_t esp0;
    uint32_t ss0;
    uint32_t esp1;
    uint32_t ss1;
    uint32_t esp2;
    uint32_t ss2;
    uint32_t cr3;
    uint32_t eip;
    uint32_t eflags;
    uint32_t eax;
    uint32_t ecx;
    uint32_t edx;
    uint32_t ebx;
    uint32_t esp;
    uint32_t ebp;
    uint32_t esi;
    uint32_t edi;
    uint32_t es;
    uint32_t cs;
    uint32_t ss;
    uint32_t ds;
    uint32_t fs;
    uint32_t gs;
    uint32_t ldt;
    uint16_t trap;
    uint16_t iomap_base;
} __attribute__((packed)) tss_entry_t;

static struct gdt_entry gdt[6];
static struct gdt_ptr gdtp;
static tss_entry_t kernel_tss;
static uint8_t g_user_mode_ready = 0;
static uint8_t g_tss_ready = 0;

static void gdt_set_gate(int index, uint32_t base, uint32_t limit, uint8_t access, uint8_t granularity) {
    gdt[index].base_low = (uint16_t)(base & 0xFFFF);
    gdt[index].base_middle = (uint8_t)((base >> 16) & 0xFF);
    gdt[index].base_high = (uint8_t)((base >> 24) & 0xFF);
    gdt[index].limit_low = (uint16_t)(limit & 0xFFFF);
    gdt[index].granularity = (uint8_t)(((limit >> 16) & 0x0F) | (granularity & 0xF0));
    gdt[index].access = access;
}

static void gdt_initialize_tss(void) {
    uint8_t* bytes = (uint8_t*)&kernel_tss;
    for (uint32_t i = 0; i < sizeof(kernel_tss); ++i) {
        bytes[i] = 0;
    }

    kernel_tss.ss0 = gdt_kernel_data_selector();
    kernel_tss.iomap_base = sizeof(kernel_tss);
    kernel_tss.cs = (uint32_t)gdt_user_code_selector();
    kernel_tss.ss = (uint32_t)gdt_user_data_selector();
    kernel_tss.ds = (uint32_t)gdt_user_data_selector();
    kernel_tss.es = (uint32_t)gdt_user_data_selector();
    kernel_tss.fs = (uint32_t)gdt_user_data_selector();
    kernel_tss.gs = (uint32_t)gdt_user_data_selector();

    gdt_set_gate(5, (uint32_t)&kernel_tss, sizeof(kernel_tss) - 1u, 0x89, 0x40);
}

void gdt_initialize(void) {
    gdtp.limit = (uint16_t)(sizeof(gdt) - 1);
    gdtp.base = (uint32_t)&gdt;

    gdt_set_gate(0, 0, 0, 0, 0);
    gdt_set_gate(1, 0, 0xFFFFFFFFu, 0x9A, 0xCF);
    gdt_set_gate(2, 0, 0xFFFFFFFFu, 0x92, 0xCF);
    gdt_set_gate(3, 0, 0xFFFFFFFFu, 0xFA, 0xCF);
    gdt_set_gate(4, 0, 0xFFFFFFFFu, 0xF2, 0xCF);
    gdt_initialize_tss();

    __asm__ __volatile__(
        "lgdt (%0)\n"
        "movw $0x10, %%ax\n"
        "movw %%ax, %%ds\n"
        "movw %%ax, %%es\n"
        "movw %%ax, %%fs\n"
        "movw %%ax, %%gs\n"
        "movw %%ax, %%ss\n"
        "ljmp $0x08, $.gdt_flush\n"
        ".gdt_flush:\n"
        :
        : "r"(&gdtp)
        : "ax", "memory"
    );

    __asm__ __volatile__("ltr %%ax" : : "a"(gdt_tss_selector()) : "memory");

    g_user_mode_ready = 1;
    g_tss_ready = 1;
}

void gdt_set_kernel_stack(uint32_t stack_top) {
    kernel_tss.esp0 = stack_top;
}

uint8_t gdt_user_mode_ready(void) {
    return g_user_mode_ready;
}

uint8_t gdt_tss_ready(void) {
    return g_tss_ready;
}

uint16_t gdt_kernel_code_selector(void) {
    return 0x08;
}

uint16_t gdt_kernel_data_selector(void) {
    return 0x10;
}

uint16_t gdt_user_code_selector(void) {
    return 0x1B;
}

uint16_t gdt_user_data_selector(void) {
    return 0x23;
}

uint16_t gdt_tss_selector(void) {
    return 0x28;
}

uint32_t gdt_kernel_stack_top(void) {
    return kernel_tss.esp0;
}
