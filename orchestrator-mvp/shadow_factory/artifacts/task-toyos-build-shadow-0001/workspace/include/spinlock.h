#ifndef SPINLOCK_H
#define SPINLOCK_H

#include <stdint.h>

typedef struct {
    volatile uint32_t value;
} spinlock_t;

static inline void spinlock_initialize(spinlock_t* lock) {
    lock->value = 0;
}

static inline void spinlock_acquire(spinlock_t* lock) {
    uint32_t previous;
    for (;;) {
        previous = 1;
        __asm__ __volatile__("xchg %0, %1" : "+r"(previous), "+m"(lock->value) : : "memory");
        if (previous == 0) {
            return;
        }
        while (lock->value != 0) {
            __asm__ __volatile__("pause");
        }
    }
}

static inline void spinlock_release(spinlock_t* lock) {
    __asm__ __volatile__("movl $0, %0" : "+m"(lock->value) : : "memory");
}

#endif
