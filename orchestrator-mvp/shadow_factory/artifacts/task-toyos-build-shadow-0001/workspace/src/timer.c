#include "timer.h"

#include "idt.h"
#include "io.h"
#include "scheduler.h"

static uint32_t g_timer_ticks = 0;
static uint32_t g_timer_frequency = 0;

static void timer_interrupt_handler(uint32_t vector, register_frame_t* frame) {
    (void)vector;
    (void)frame;
    ++g_timer_ticks;
    scheduler_tick();
}

void timer_initialize(uint32_t frequency_hz) {
    uint32_t divisor;

    if (frequency_hz == 0) {
        frequency_hz = 100;
    }
    g_timer_frequency = frequency_hz;
    divisor = 1193180u / frequency_hz;

    outb(0x43, 0x36);
    outb(0x40, (uint8_t)(divisor & 0xFF));
    outb(0x40, (uint8_t)((divisor >> 8) & 0xFF));

    register_interrupt_handler(0x20, timer_interrupt_handler);
}

uint32_t timer_ticks(void) {
    return g_timer_ticks;
}

uint32_t timer_frequency(void) {
    return g_timer_frequency;
}
