#ifndef SCHEDULER_H
#define SCHEDULER_H

#include <stddef.h>
#include <stdint.h>

typedef uint32_t pid_t;
typedef void (*process_entry_t)(void* context);

typedef enum {
    PROCESS_PRIVILEGE_KERNEL = 0,
    PROCESS_PRIVILEGE_USER = 3,
} process_privilege_t;

typedef enum {
    PROCESS_READY = 0,
    PROCESS_RUNNING = 1,
    PROCESS_BLOCKED = 2,
    PROCESS_EXITED = 3,
} process_state_t;

typedef struct {
    pid_t pid;
    const char* name;
    process_entry_t entry;
    void* context;
    uint32_t runs;
    uint32_t priority;
    process_privilege_t privilege;
    process_state_t state;
    uint32_t time_slice;
    uint32_t slice_remaining;
    int32_t exit_code;
    uintptr_t entry_point;
    uintptr_t kernel_stack_base;
    uintptr_t kernel_stack_top;
    uintptr_t user_stack_base;
    uintptr_t user_stack_top;
    uint8_t active;
    uint8_t started;
    uint8_t ring3_ready;
} process_t;

void scheduler_initialize(void);
pid_t scheduler_create_process(const char* name, process_entry_t entry, void* context, process_privilege_t privilege, uint32_t priority, uint32_t time_slice);
int scheduler_destroy_process(pid_t pid);
void scheduler_tick(void);
void scheduler_dispatch_once(void);
void scheduler_run_rounds(uint32_t rounds);
void scheduler_yield_current(void);
void scheduler_mark_current_exited(int32_t exit_code);
int scheduler_enter_user_process(pid_t pid);
void scheduler_request_ring0_return(void);
uint8_t scheduler_ring3_active(void);
void* scheduler_current_user_context(void);
uint32_t scheduler_ticks(void);
pid_t scheduler_current_pid(void);
size_t scheduler_current_index(void);
size_t scheduler_process_count(void);
uint32_t scheduler_ring3_ready_count(void);
const process_t* scheduler_get_process(size_t index);
const process_t* scheduler_current_process(void);

#endif
