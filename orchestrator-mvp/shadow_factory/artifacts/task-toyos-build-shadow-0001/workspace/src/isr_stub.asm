[bits 32]
global isr_default_stub
global isr_irq0_stub
global isr_irq1_stub
global isr_syscall_stub
global isr_err10_stub
global isr_err11_stub
global isr_err12_stub
global isr_err13_stub
global isr_err14_stub
global scheduler_iret_to_user
global toy_user_logger_stub
extern isr_dispatch_handler
extern scheduler_ring3_saved_esp
extern scheduler_ring3_return_requested

%macro ISR_STUB 2
%1:
    pusha
    mov eax, esp
    push eax
    push dword %2
    call isr_dispatch_handler
    add esp, 8
    popa
    iretd
%endmacro

%macro ISR_ERR_STUB 2
%1:
    pusha
    mov eax, esp
    push eax
    push dword %2
    call isr_dispatch_handler
    add esp, 8
    popa
    add esp, 4
    iretd
%endmacro

section .text
ISR_STUB isr_default_stub, 255
ISR_STUB isr_irq0_stub, 0x20
ISR_STUB isr_irq1_stub, 0x21
ISR_ERR_STUB isr_err10_stub, 0x0A
ISR_ERR_STUB isr_err11_stub, 0x0B
ISR_ERR_STUB isr_err12_stub, 0x0C
ISR_ERR_STUB isr_err13_stub, 0x0D
ISR_ERR_STUB isr_err14_stub, 0x0E

isr_syscall_stub:
    pusha
    mov eax, esp
    push eax
    push dword 0x80
    call isr_dispatch_handler
    add esp, 8
    popa
    cmp dword [scheduler_ring3_return_requested], 0
    je .sysret
    mov dword [scheduler_ring3_return_requested], 0
    mov esp, [scheduler_ring3_saved_esp]
    ret
.sysret:
    iretd

scheduler_iret_to_user:
    mov [scheduler_ring3_saved_esp], esp
    mov ax, 0x23
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov eax, [esp + 4]
    mov edx, [esp + 8]
    mov ecx, [esp + 12]
    push dword 0x23
    push edx
    push dword 0x202
    push dword 0x1B
    push dword scheduler_user_entry_trampoline
    iretd

toy_user_logger_stub:
    mov eax, 4
    xor ebx, ebx
    xor ecx, ecx
    xor edx, edx
    xor esi, esi
    int 0x80
    mov eax, 1
    mov ebx, [esp + 4]
    mov ebx, [ebx + 4]
    xor ecx, ecx
    xor edx, edx
    xor esi, esi
    int 0x80
    mov eax, 3
    xor ebx, ebx
    xor ecx, ecx
    xor edx, edx
    xor esi, esi
    int 0x80
.user_hang:
    hlt
    jmp .user_hang

scheduler_user_entry_trampoline:
    push ecx
    call eax
    add esp, 4
    mov eax, 3
    xor ebx, ebx
    xor ecx, ecx
    xor edx, edx
    xor esi, esi
    int 0x80
.hang:
    hlt
    jmp .hang

section .note.GNU-stack noalloc noexec nowrite progbits
