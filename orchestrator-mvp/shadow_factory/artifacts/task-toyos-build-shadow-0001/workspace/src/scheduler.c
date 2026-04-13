#include "scheduler.h"

#include "gdt.h"
#include "io.h"
#include "memory.h"

extern void scheduler_iret_to_user(uint32_t entry, uint32_t user_stack, uint32_t arg);
uintptr_t scheduler_ring3_saved_esp = 0;
uint32_t scheduler_ring3_return_requested = 0;

#define MAX_PROCESSES 12
#define PROCESS_STACK_BYTES 4096u

static process_t processes[MAX_PROCESSES];
static size_t current_process_index = 0;
static uint32_t tick_count = 0;
static pid_t next_pid = 1;
static uint8_t ring3_active = 0;
static pid_t ring3_pid = 0;

static void scheduler_debug(const char* text) {
    if (!text) {
        return;
    }
    while (*text) {
        outb(0xE9, (uint8_t)*text++);
    }
    outb(0xE9, (uint8_t)'\r');
    outb(0xE9, (uint8_t)'\n');
}

static process_t* scheduler_find_process_mut(pid_t pid) {
    for (size_t i = 0; i < MAX_PROCESSES; ++i) {
        if (processes[i].pid == pid && (processes[i].active || processes[i].state == PROCESS_EXITED)) {
            return &processes[i];
        }
    }
    return 0;
}

static void scheduler_reset_process(process_t* process) {
    process->pid = 0;
    process->name = 0;
    process->entry = 0;
    process->context = 0;
    process->runs = 0;
    process->priority = 1;
    process->privilege = PROCESS_PRIVILEGE_KERNEL;
    process->state = PROCESS_EXITED;
    process->time_slice = 1;
    process->slice_remaining = 1;
    process->exit_code = 0;
    process->entry_point = 0;
    process->kernel_stack_base = 0;
    process->kernel_stack_top = 0;
    process->user_stack_base = 0;
    process->user_stack_top = 0;
    process->active = 0;
    process->started = 0;
    process->ring3_ready = 0;
}

static void scheduler_release_process_stacks(process_t* process) {
    if (process->kernel_stack_base != 0) {
        page_free((void*)process->kernel_stack_base);
        process->kernel_stack_base = 0;
        process->kernel_stack_top = 0;
    }
    if (process->user_stack_base != 0) {
        page_free((void*)process->user_stack_base);
        process->user_stack_base = 0;
        process->user_stack_top = 0;
    }
    process->ring3_ready = 0;
}

void scheduler_initialize(void) {
    current_process_index = 0;
    tick_count = 0;
    next_pid = 1;
    for (size_t i = 0; i < MAX_PROCESSES; ++i) {
        scheduler_reset_process(&processes[i]);
    }
}

pid_t scheduler_create_process(const char* name, process_entry_t entry, void* context, process_privilege_t privilege, uint32_t priority, uint32_t time_slice) {
    if (entry == 0) {
        return 0;
    }
    for (size_t i = 0; i < MAX_PROCESSES; ++i) {
        void* kernel_stack;
        void* user_stack;
        if (processes[i].active) {
            continue;
        }

        scheduler_reset_process(&processes[i]);
        kernel_stack = page_alloc();
        if (!kernel_stack) {
            return 0;
        }
        user_stack = 0;
        if (privilege == PROCESS_PRIVILEGE_USER) {
            user_stack = page_alloc();
            if (!user_stack) {
                page_free(kernel_stack);
                return 0;
            }
        }

        processes[i].pid = next_pid++;
        processes[i].name = name;
        processes[i].entry = entry;
        processes[i].context = context;
        processes[i].runs = 0;
        processes[i].priority = priority == 0 ? 1 : priority;
        processes[i].privilege = privilege;
        processes[i].state = PROCESS_READY;
        processes[i].time_slice = time_slice == 0 ? 1 : time_slice;
        processes[i].slice_remaining = processes[i].time_slice;
        processes[i].exit_code = 0;
        processes[i].entry_point = (uintptr_t)entry;
        processes[i].kernel_stack_base = (uintptr_t)kernel_stack;
        processes[i].kernel_stack_top = (uintptr_t)kernel_stack + PROCESS_STACK_BYTES;
        processes[i].user_stack_base = (uintptr_t)user_stack;
        processes[i].user_stack_top = user_stack ? ((uintptr_t)user_stack + PROCESS_STACK_BYTES) : 0;
        processes[i].active = 1;
        processes[i].started = 0;
        processes[i].ring3_ready = privilege == PROCESS_PRIVILEGE_USER && user_stack != 0;
        return processes[i].pid;
    }
    return 0;
}

int scheduler_destroy_process(pid_t pid) {
    process_t* process = scheduler_find_process_mut(pid);
    if (!process) {
        return -1;
    }
    scheduler_release_process_stacks(process);
    process->active = 0;
    process->state = PROCESS_EXITED;
    process->exit_code = 0;
    return 0;
}

void scheduler_tick(void) {
    ++tick_count;
    if (MAX_PROCESSES == 0) {
        return;
    }
    process_t* process = &processes[current_process_index];
    if (!process->active || process->state == PROCESS_EXITED || process->state == PROCESS_BLOCKED) {
        current_process_index = (current_process_index + 1) % MAX_PROCESSES;
        return;
    }
    if (process->slice_remaining > 0) {
        --process->slice_remaining;
    }
    if (process->slice_remaining == 0) {
        if (process->state == PROCESS_RUNNING) {
            process->state = PROCESS_READY;
        }
        process->slice_remaining = process->time_slice;
        current_process_index = (current_process_index + 1) % MAX_PROCESSES;
    }
}

int scheduler_enter_user_process(pid_t pid) {
    process_t* process = scheduler_find_process_mut(pid);
    uint32_t previous_esp0;
    if (!process || !process->active || process->privilege != PROCESS_PRIVILEGE_USER || !process->ring3_ready) {
        return -1;
    }
    scheduler_debug("SCHED: enter user start");
    previous_esp0 = gdt_kernel_stack_top();
    current_process_index = (size_t)(process - processes);
    process->state = PROCESS_RUNNING;
    process->started = 1;
    ring3_active = 1;
    ring3_pid = pid;
    scheduler_ring3_return_requested = 0;
    gdt_set_kernel_stack((uint32_t)process->kernel_stack_top);
    scheduler_debug("SCHED: iret handoff");
    scheduler_iret_to_user((uint32_t)process->entry_point, (uint32_t)process->user_stack_top, (uint32_t)process->context);
    scheduler_debug("SCHED: user returned");
    ring3_active = 0;
    ring3_pid = 0;
    __asm__ __volatile__(
        "movw $0x10, %%ax\n"
        "movw %%ax, %%ds\n"
        "movw %%ax, %%es\n"
        "movw %%ax, %%fs\n"
        "movw %%ax, %%gs\n"
        :
        :
        : "ax", "memory"
    );
    gdt_set_kernel_stack(previous_esp0);
    ++process->runs;
    if (process->state == PROCESS_RUNNING) {
        process->state = PROCESS_READY;
    }
    if (process->state == PROCESS_EXITED) {
        process->active = 0;
    }
    return 0;
}

void scheduler_dispatch_once(void) {
    for (size_t offset = 0; offset < MAX_PROCESSES; ++offset) {
        size_t index = (current_process_index + offset) % MAX_PROCESSES;
        process_t* process = &processes[index];
        if (!process->active || process->entry == 0 || process->state == PROCESS_BLOCKED || process->state == PROCESS_EXITED) {
            continue;
        }
        current_process_index = index;
        if (process->privilege == PROCESS_PRIVILEGE_USER && process->ring3_ready) {
            scheduler_debug("SCHED: dispatch user");
            (void)scheduler_enter_user_process(process->pid);
            return;
        }
        process->state = PROCESS_RUNNING;
        process->started = 1;
        process->entry(process->context);
        ++process->runs;
        if (process->state == PROCESS_RUNNING) {
            process->state = PROCESS_READY;
        }
        if (process->state == PROCESS_EXITED) {
            process->active = 0;
        }
        return;
    }
}

void scheduler_run_rounds(uint32_t rounds) {
    for (uint32_t round = 0; round < rounds; ++round) {
        for (size_t i = 0; i < MAX_PROCESSES; ++i) {
            scheduler_dispatch_once();
            scheduler_tick();
        }
    }
}

void scheduler_yield_current(void) {
    processes[current_process_index].slice_remaining = 0;
}

void scheduler_mark_current_exited(int32_t exit_code) {
    processes[current_process_index].exit_code = exit_code;
    processes[current_process_index].state = PROCESS_EXITED;
    processes[current_process_index].active = 0;
}

uint32_t scheduler_ticks(void) {
    return tick_count;
}

pid_t scheduler_current_pid(void) {
    return processes[current_process_index].pid;
}

size_t scheduler_current_index(void) {
    return current_process_index;
}

size_t scheduler_process_count(void) {
    size_t count = 0;
    for (size_t i = 0; i < MAX_PROCESSES; ++i) {
        if (processes[i].pid != 0) {
            ++count;
        }
    }
    return count;
}

uint32_t scheduler_ring3_ready_count(void) {
    uint32_t count = 0;
    for (size_t i = 0; i < MAX_PROCESSES; ++i) {
        if (processes[i].ring3_ready) {
            ++count;
        }
    }
    return count;
}

const process_t* scheduler_get_process(size_t index) {
    if (index >= MAX_PROCESSES || processes[index].pid == 0) {
        return 0;
    }
    return &processes[index];
}

const process_t* scheduler_current_process(void) {
    if (processes[current_process_index].pid == 0) {
        return 0;
    }
    return &processes[current_process_index];
}

void scheduler_request_ring0_return(void) {
    scheduler_ring3_return_requested = 1;
}

uint8_t scheduler_ring3_active(void) {
    return ring3_active;
}

void* scheduler_current_user_context(void) {
    if (!ring3_active) {
        return 0;
    }
    return processes[current_process_index].context;
}
