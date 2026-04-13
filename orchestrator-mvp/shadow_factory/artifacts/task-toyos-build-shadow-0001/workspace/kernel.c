#include <stddef.h>
#include <stdint.h>

#include "block_device.h"
#include "gdt.h"
#include "idt.h"
#include "io.h"
#include "keyboard.h"
#include "memory.h"
#include "paging.h"
#include "panic.h"
#include "scheduler.h"
#include "syscall.h"
#include "terminal.h"
#include "timer.h"
#include "vfs.h"

#define PROCESS_SLOTS 12u

extern void toy_user_logger_stub(void* context);

typedef struct {
    const char* file_name;
    const char* payload;
    uint32_t limit;
    uint32_t runs;
} process_context_t;

typedef struct {
    uint8_t started;
    uint8_t prompt_ready;
    uint8_t line_length;
    char line[64];
} shell_context_t;

typedef struct {
    uint8_t completed;
} probe_context_t;

typedef struct {
    uint8_t completed;
} shell_probe_context_t;

typedef struct {
    uint8_t completed;
} fs_stress_context_t;

typedef struct {
    const char* label;
    const char* ramfs_file;
    const char* ramfs_payload;
    const char* tinyfs_file;
    const char* tinyfs_payload;
    uint8_t phase;
    uint8_t completed;
} fs_writer_context_t;

typedef struct {
    uint8_t completed;
} fs_multi_verify_context_t;

typedef struct {
    uint8_t phase;
    uint8_t completed;
} fs_mixed_probe_context_t;

static void user_shell_execute(shell_context_t* shell);
static fs_writer_context_t fs_writer_a_ctx;
static fs_writer_context_t fs_writer_b_ctx;

static void debug_port_write_char(char ch) {
    outb(0xE9, (uint8_t)ch);
}

static void debug_port_write(const char* text) {
    if (!text) {
        return;
    }
    while (*text) {
        debug_port_write_char(*text++);
    }
}

static void debug_port_writeln(const char* text) {
    debug_port_write(text);
    debug_port_write("\r\n");
}

static void debug_port_write_dec(uint32_t value) {
    char buffer[24];
    size_t index = 0;

    if (value == 0) {
        debug_port_write_char('0');
        return;
    }

    while (value > 0 && index < sizeof(buffer)) {
        buffer[index++] = (char)('0' + (value % 10));
        value /= 10;
    }

    while (index > 0) {
        debug_port_write_char(buffer[--index]);
    }
}

static void maybe_run_paging_stage1_smoke(void) {
#if TOYOS_EXPERIMENTAL_PAGING_STAGE1
    debug_port_writeln("ToyOS: paging stage1 pre-enable");
    if (!paging_stage1_smoke_enable()) {
        debug_port_writeln("ToyOS: paging stage1 fallback panic");
        panic("paging stage1 smoke failed");
    }
    debug_port_writeln("ToyOS: paging stage1 post-enable");
#else
    debug_port_writeln("ToyOS: paging stage1 skipped (stable path)");
#endif
}

static void terminal_write_char(char ch) {
    char text[2];
    text[0] = ch;
    text[1] = '\0';
    terminal_write(text);
}

static void terminal_write_dec(size_t value) {
    char buffer[24];
    size_t index = 0;

    if (value == 0) {
        terminal_write("0");
        return;
    }

    while (value > 0 && index < sizeof(buffer)) {
        buffer[index++] = (char)('0' + (value % 10));
        value /= 10;
    }

    while (index > 0) {
        terminal_write_char(buffer[--index]);
    }
}

static void terminal_write_key_value(const char* key, size_t value) {
    terminal_write(key);
    terminal_write(": ");
    terminal_write_dec(value);
    terminal_writeln("");
}

static uint32_t user_syscall(uint32_t number, uint32_t arg0, uint32_t arg1, uint32_t arg2, uint32_t arg3) {
    return syscall_invoke(number, arg0, arg1, arg2, arg3);
}

static void user_console_write(const char* text) {
    user_syscall(SYSCALL_CONSOLE_WRITE, (uint32_t)(uintptr_t)text, 0, 0, 0);
}

static void user_write_log(const char* text) {
    user_syscall(SYSCALL_WRITE_LOG, (uint32_t)(uintptr_t)text, 0, 0, 0);
}

static uint32_t user_current_pid(void) {
    return user_syscall(SYSCALL_QUERY_PID, 0, 0, 0, 0);
}

static uint32_t user_tick_count(void) {
    return user_syscall(SYSCALL_QUERY_TICKS, 0, 0, 0, 0);
}

static uint32_t user_heap_used(void) {
    return user_syscall(SYSCALL_QUERY_HEAP_USED, 0, 0, 0, 0);
}

static uint32_t user_pages_used(void) {
    return user_syscall(SYSCALL_QUERY_PAGES_USED, 0, 0, 0, 0);
}

static uint32_t user_ramfs_count(void) {
    return user_syscall(SYSCALL_RAMFS_COUNT, 0, 0, 0, 0);
}

static uint32_t user_tinyfs_count(void) {
    return user_syscall(SYSCALL_TINYFS_COUNT, 0, 0, 0, 0);
}

static int user_fetch_file_name(uint32_t syscall_number, uint32_t index, char* out, size_t capacity) {
    uint32_t result = user_syscall(syscall_number, index, (uint32_t)(uintptr_t)out, (uint32_t)capacity, 0);
    return result >= 0xFFFFFFFEu ? -1 : 0;
}

static int user_read_fs_text(uint32_t syscall_number, const char* path, char* out, size_t capacity) {
    uint32_t result = user_syscall(syscall_number, (uint32_t)(uintptr_t)path, (uint32_t)(uintptr_t)out, (uint32_t)capacity, 0);
    return result == 0 ? 0 : -1;
}

static uint32_t user_invalid_syscall_probe(void) {
    return user_syscall(0xDEADu, 0, 0, 0, 0);
}

static int user_read_key(void) {
    uint32_t value = user_syscall(SYSCALL_READ_KEY, 0, 0, 0, 0);
    return value == 0xFFFFFFFFu ? -1 : (int)value;
}

static void user_write_dec(uint32_t value) {
    char buffer[24];
    size_t index = 0;
    if (value == 0) {
        user_console_write("0");
        return;
    }
    while (value > 0 && index < sizeof(buffer)) {
        buffer[index++] = (char)('0' + (value % 10));
        value /= 10;
    }
    while (index > 0) {
        char out[2] = { buffer[--index], '\0' };
        user_console_write(out);
    }
}

static int shell_equals(const char* left, const char* right) {
    size_t index = 0;
    while (left[index] != '\0' && right[index] != '\0') {
        if (left[index] != right[index]) {
            return 0;
        }
        ++index;
    }
    return left[index] == right[index];
}

static int shell_starts_with(const char* text, const char* prefix) {
    size_t index = 0;
    while (prefix[index] != '\0') {
        if (text[index] != prefix[index]) {
            return 0;
        }
        ++index;
    }
    return 1;
}

static const char* shell_skip_spaces(const char* text) {
    while (*text == ' ') {
        ++text;
    }
    return text;
}

static void user_list_named_fs(const char* label, uint32_t count, uint32_t name_syscall) {
    char name[32];
    user_console_write("\n[");
    user_console_write(label);
    user_console_write("]\n");
    for (uint32_t i = 0; i < count; ++i) {
        if (user_fetch_file_name(name_syscall, i, name, sizeof(name)) != 0) {
            continue;
        }
        user_console_write(" - ");
        user_console_write(name);
        user_console_write("\n");
    }
}

static void user_list_all_files(void) {
    user_list_named_fs("ramfs", user_ramfs_count(), SYSCALL_RAMFS_NAME);
    user_list_named_fs("tinyfs", user_tinyfs_count(), SYSCALL_TINYFS_NAME);
}

static int user_print_file_contents(const char* path) {
    char buffer[160];
    if (user_read_fs_text(SYSCALL_RAMFS_READ, path, buffer, sizeof(buffer)) == 0) {
        user_console_write("\n[ramfs] ");
        user_console_write(path);
        user_console_write(": ");
        user_console_write(buffer);
        user_console_write("\n");
        return 0;
    }
    if (user_read_fs_text(SYSCALL_TINYFS_READ, path, buffer, sizeof(buffer)) == 0) {
        user_console_write("\n[tinyfs] ");
        user_console_write(path);
        user_console_write(": ");
        user_console_write(buffer);
        user_console_write("\n");
        return 0;
    }
    return -1;
}

static void shell_load_command(shell_context_t* shell, const char* command) {
    size_t index = 0;
    if (!shell || !command) {
        return;
    }
    while (command[index] != '\0' && index + 1u < sizeof(shell->line)) {
        shell->line[index] = command[index];
        ++index;
    }
    shell->line_length = (uint8_t)index;
    shell->line[index] = '\0';
}

static void shell_run_scripted_command(shell_context_t* shell, const char* command) {
    shell_load_command(shell, command);
    user_console_write("\n[shell-probe] command=");
    user_console_write(command);
    user_console_write("\n");
    user_shell_execute(shell);
}

static void user_shell_execute(shell_context_t* shell) {
    const char* path;
    shell->line[shell->line_length] = '\0';
    if (shell->line_length == 0) {
        user_console_write("\n");
        shell->prompt_ready = 0;
        return;
    }
    if (shell_equals(shell->line, "help")) {
        user_console_write("\ncommands: help pid ticks mem pages ls cat <path> exit\n");
    } else if (shell_equals(shell->line, "pid")) {
        user_console_write("\npid=");
        user_write_dec(user_current_pid());
        user_console_write("\n");
    } else if (shell_equals(shell->line, "ticks")) {
        user_console_write("\nticks=");
        user_write_dec(user_tick_count());
        user_console_write("\n");
    } else if (shell_equals(shell->line, "mem")) {
        user_console_write("\nheap=");
        user_write_dec(user_heap_used());
        user_console_write(" bytes\n");
    } else if (shell_equals(shell->line, "pages")) {
        user_console_write("\npages-used=");
        user_write_dec(user_pages_used());
        user_console_write("\n");
    } else if (shell_equals(shell->line, "ls")) {
        user_list_all_files();
    } else if (shell_starts_with(shell->line, "cat ")) {
        path = shell_skip_spaces(shell->line + 4);
        if (*path == '\0') {
            user_console_write("\nusage: cat <path>\n");
        } else if (user_print_file_contents(path) != 0) {
            user_console_write("\nfile not found: ");
            user_console_write(path);
            user_console_write("\n");
        }
    } else if (shell_equals(shell->line, "exit")) {
        user_console_write("\nuser shell exit\n");
        user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
        return;
    } else {
        user_console_write("\nunknown command: ");
        user_console_write(shell->line);
        user_console_write("\n");
    }
    shell->line_length = 0;
    shell->prompt_ready = 0;
}

static void toy_user_probe_process(void* raw_context) {
    probe_context_t* probe = (probe_context_t*)raw_context;
    char buffer[160];
    char second_buffer[160];
    char name[32];

    if (probe->completed) {
        user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
        return;
    }

    user_console_write("\n[user-probe] checking VFS syscalls\n");
    user_console_write("ramfs-files=");
    user_write_dec(user_ramfs_count());
    user_console_write(" tinyfs-files=");
    user_write_dec(user_tinyfs_count());
    user_console_write("\n");

    if (user_fetch_file_name(SYSCALL_TINYFS_NAME, 0, name, sizeof(name)) == 0) {
        user_console_write("tinyfs[0]=");
        user_console_write(name);
        user_console_write("\n");
    }
    if (user_read_fs_text(SYSCALL_TINYFS_READ, "etc/motd", buffer, sizeof(buffer)) == 0) {
        user_console_write("motd=");
        user_console_write(buffer);
        user_console_write("\n");
        if (user_read_fs_text(SYSCALL_TINYFS_READ, "etc/motd", second_buffer, sizeof(second_buffer)) == 0) {
            user_console_write("motd-repeat-match=");
            user_write_dec(shell_equals(buffer, second_buffer) ? 1u : 0u);
            user_console_write("\n");
        }
    }
    if (user_read_fs_text(SYSCALL_RAMFS_READ, "proc/drivers", buffer, sizeof(buffer)) == 0) {
        user_console_write("drivers=");
        user_console_write(buffer);
        user_console_write("\n");
    }
    user_console_write("missing-read-status=");
    user_write_dec(user_read_fs_text(SYSCALL_TINYFS_READ, "missing/file.txt", buffer, sizeof(buffer)) == 0 ? 0u : 1u);
    user_console_write("\n");
    user_console_write("empty-path-status=");
    user_write_dec(user_read_fs_text(SYSCALL_RAMFS_READ, "", buffer, sizeof(buffer)) == 0 ? 0u : 1u);
    user_console_write("\n");

    user_console_write("invalid-syscall-status=");
    user_write_dec(user_invalid_syscall_probe());
    user_console_write("\n");

    user_write_log("ToyOS: user probe complete");
    probe->completed = 1;
    user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
}

static void toy_user_shell_process(void* raw_context) {
    shell_context_t* shell = (shell_context_t*)raw_context;
    if (!shell->started) {
        user_console_write("\n[user-shell] online\n");
        user_console_write("type help, pid, ticks, mem, pages, ls, cat <path>, exit\n");
        shell->started = 1;
        shell->prompt_ready = 0;
        shell->line_length = 0;
    }
    if (!shell->prompt_ready) {
        user_console_write("shell> ");
        shell->prompt_ready = 1;
    }
    for (uint32_t attempt = 0; attempt < 4; ++attempt) {
        int ch = user_read_key();
        if (ch < 0) {
            break;
        }
        if (ch == '\r' || ch == '\n') {
            user_shell_execute(shell);
            user_syscall(SYSCALL_YIELD, 0, 0, 0, 0);
            return;
        }
        if ((ch == '\b' || ch == 127) && shell->line_length > 0) {
            shell->line_length -= 1;
            continue;
        }
        if ((size_t)shell->line_length + 1u < sizeof(shell->line)) {
            shell->line[shell->line_length++] = (char)ch;
            char out[2] = { (char)ch, '\0' };
            user_console_write(out);
        }
    }
    user_syscall(SYSCALL_YIELD, 0, 0, 0, 0);
}

static void toy_user_fs_mixed_probe_process(void* raw_context) {
    fs_mixed_probe_context_t* context = (fs_mixed_probe_context_t*)raw_context;
    char buffer[160];

    if (context->completed) {
        user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
        return;
    }

    if (!fs_writer_a_ctx.completed || !fs_writer_b_ctx.completed) {
        user_syscall(SYSCALL_YIELD, 0, 0, 0, 0);
        return;
    }

    if (context->phase == 0) {
        user_write_log("ToyOS: fs mixed probe start");
        if (user_read_fs_text(SYSCALL_RAMFS_READ, fs_writer_a_ctx.ramfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_a_ctx.ramfs_payload)) {
            user_write_log("ToyOS: fs mixed probe ramfs a fault");
            user_syscall(SYSCALL_EXIT, 1, 0, 0, 0);
            return;
        }
        if (user_read_fs_text(SYSCALL_TINYFS_READ, fs_writer_a_ctx.tinyfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_a_ctx.tinyfs_payload)) {
            user_write_log("ToyOS: fs mixed probe tinyfs a fault");
            user_syscall(SYSCALL_EXIT, 1, 0, 0, 0);
            return;
        }
        user_write_log("ToyOS: fs mixed probe phase1");
        context->phase = 1;
        user_syscall(SYSCALL_YIELD, 0, 0, 0, 0);
        return;
    }

    if (user_read_fs_text(SYSCALL_RAMFS_READ, fs_writer_b_ctx.ramfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_b_ctx.ramfs_payload)) {
        user_write_log("ToyOS: fs mixed probe ramfs b fault");
        user_syscall(SYSCALL_EXIT, 1, 0, 0, 0);
        return;
    }
    if (user_read_fs_text(SYSCALL_TINYFS_READ, fs_writer_b_ctx.tinyfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_b_ctx.tinyfs_payload)) {
        user_write_log("ToyOS: fs mixed probe tinyfs b fault");
        user_syscall(SYSCALL_EXIT, 1, 0, 0, 0);
        return;
    }
    user_write_log("ToyOS: fs mixed probe complete");
    context->completed = 1;
    user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
}

static void toy_user_shell_probe_process(void* raw_context) {
    shell_probe_context_t* probe = (shell_probe_context_t*)raw_context;
    shell_context_t scripted_shell = {0};

    if (probe->completed) {
        user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
        return;
    }

    user_console_write("\n[shell-probe] start\n");
    shell_run_scripted_command(&scripted_shell, "help");
    shell_run_scripted_command(&scripted_shell, "ls");
    shell_run_scripted_command(&scripted_shell, "cat etc/motd");
    shell_run_scripted_command(&scripted_shell, "cat etc/motd");
    shell_run_scripted_command(&scripted_shell, "cat proc/drivers");
    shell_run_scripted_command(&scripted_shell, "cat missing/file.txt");
    user_write_log("ToyOS: shell probe complete");
    probe->completed = 1;
    user_syscall(SYSCALL_EXIT, 0, 0, 0, 0);
}

static void kernel_fs_stress_process(void* raw_context) {
    fs_stress_context_t* context = (fs_stress_context_t*)raw_context;
    char ramfs_buffer[160];
    char tinyfs_buffer[160];
    const char* ramfs_payload = "ramfs stress payload stable";
    const char* tinyfs_payload = "tinyfs stress payload stable";

    if (context->completed) {
        scheduler_mark_current_exited(0);
        return;
    }

    debug_port_writeln("ToyOS: fs stress start");
    if (ramfs_write_text("tmp/fs-stress.log", ramfs_payload) != 0) {
        panic("ramfs stress write failed");
    }
    if (ramfs_read_text("tmp/fs-stress.log", ramfs_buffer, sizeof(ramfs_buffer)) != 0) {
        panic("ramfs stress read failed");
    }
    if (!shell_equals(ramfs_buffer, ramfs_payload)) {
        panic("ramfs stress mismatch");
    }
    if (tinyfs_write_text("var/stress.txt", tinyfs_payload) != 0) {
        panic("tinyfs stress write failed");
    }
    if (tinyfs_read_text("var/stress.txt", tinyfs_buffer, sizeof(tinyfs_buffer)) != 0) {
        panic("tinyfs stress read failed");
    }
    if (!shell_equals(tinyfs_buffer, tinyfs_payload)) {
        panic("tinyfs stress mismatch");
    }
    if (tinyfs_read_text("var/stress.txt", tinyfs_buffer, sizeof(tinyfs_buffer)) != 0) {
        panic("tinyfs stress reread failed");
    }
    if (!shell_equals(tinyfs_buffer, tinyfs_payload)) {
        panic("tinyfs stress reread mismatch");
    }
    debug_port_writeln("ToyOS: fs stress verified");
    context->completed = 1;
    debug_port_writeln("ToyOS: fs stress complete");
    scheduler_mark_current_exited(0);
}

static void kernel_fs_multi_writer_process(void* raw_context) {
    fs_writer_context_t* context = (fs_writer_context_t*)raw_context;
    char ramfs_buffer[160];
    char tinyfs_buffer[160];

    if (context->completed) {
        scheduler_mark_current_exited(0);
        return;
    }

    if (context->phase == 0) {
        debug_port_write("ToyOS: fs writer ");
        debug_port_write(context->label);
        debug_port_writeln(" write");
        if (ramfs_write_text(context->ramfs_file, context->ramfs_payload) != 0) {
            panic("fs writer ramfs write failed");
        }
        if (tinyfs_write_text(context->tinyfs_file, context->tinyfs_payload) != 0) {
            panic("fs writer tinyfs write failed");
        }
        context->phase = 1;
        return;
    }

    if (ramfs_read_text(context->ramfs_file, ramfs_buffer, sizeof(ramfs_buffer)) != 0) {
        panic("fs writer ramfs read failed");
    }
    if (!shell_equals(ramfs_buffer, context->ramfs_payload)) {
        panic("fs writer ramfs mismatch");
    }
    if (tinyfs_read_text(context->tinyfs_file, tinyfs_buffer, sizeof(tinyfs_buffer)) != 0) {
        panic("fs writer tinyfs read failed");
    }
    if (!shell_equals(tinyfs_buffer, context->tinyfs_payload)) {
        panic("fs writer tinyfs mismatch");
    }
    debug_port_write("ToyOS: fs writer ");
    debug_port_write(context->label);
    debug_port_writeln(" verified");
    context->completed = 1;
    scheduler_mark_current_exited(0);
}

static void kernel_fs_multi_verify_process(void* raw_context) {
    fs_multi_verify_context_t* context = (fs_multi_verify_context_t*)raw_context;
    char buffer[160];

    if (context->completed) {
        scheduler_mark_current_exited(0);
        return;
    }
    if (!fs_writer_a_ctx.completed || !fs_writer_b_ctx.completed) {
        return;
    }

    debug_port_writeln("ToyOS: fs multi verify start");
    if (ramfs_read_text(fs_writer_a_ctx.ramfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_a_ctx.ramfs_payload)) {
        panic("fs multi verify ramfs a failed");
    }
    if (ramfs_read_text(fs_writer_b_ctx.ramfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_b_ctx.ramfs_payload)) {
        panic("fs multi verify ramfs b failed");
    }
    if (tinyfs_read_text(fs_writer_a_ctx.tinyfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_a_ctx.tinyfs_payload)) {
        panic("fs multi verify tinyfs a failed");
    }
    if (tinyfs_read_text(fs_writer_b_ctx.tinyfs_file, buffer, sizeof(buffer)) != 0 || !shell_equals(buffer, fs_writer_b_ctx.tinyfs_payload)) {
        panic("fs multi verify tinyfs b failed");
    }
    debug_port_writeln("ToyOS: fs multi verify complete");
    context->completed = 1;
    scheduler_mark_current_exited(0);
}

static fs_writer_context_t fs_writer_a_ctx = {
    "A",
    "tmp/fs-writer-a.log",
    "ramfs writer A payload",
    "var/fs-writer-a.txt",
    "tinyfs writer A payload",
    0,
    0
};

static fs_writer_context_t fs_writer_b_ctx = {
    "B",
    "tmp/fs-writer-b.log",
    "ramfs writer B payload",
    "var/fs-writer-b.txt",
    "tinyfs writer B payload",
    0,
    0
};

static fs_multi_verify_context_t fs_multi_verify_ctx = {
    0
};

static fs_mixed_probe_context_t fs_mixed_probe_ctx = {
    0,
    0
};

static void draw_status_box(void) {
    terminal_set_color(0x1F);
    terminal_writeln("============= ToyOS Kernel ============");
    terminal_set_color(0x0F);
    terminal_writeln("boot: protected mode ready");
    terminal_writeln("segments: kernel + user descriptors loaded");
    terminal_writeln("interrupts: IDT + PIC + int 0x80 syscall gate");
    terminal_writeln("memory: heap allocator + page allocator");
    terminal_writeln("storage: RAMFS + TinyFS on ramdisk");
    terminal_writeln("drivers: PIT timer + keyboard IRQ");
    terminal_writeln("processes: time-slice scheduler online");
}

static void kernel_fs_process(void* raw_context) {
    process_context_t* context = (process_context_t*)raw_context;
    if (ramfs_write_text(context->file_name, context->payload) != 0) {
        panic("kernel fs process failed to write RAMFS");
    }
    context->runs += 1;
    if (context->runs >= context->limit) {
        scheduler_mark_current_exited(0);
    }
}

static void show_memory_report(void) {
    terminal_set_color(0x0B);
    terminal_writeln("");
    terminal_writeln("[memory]");
    terminal_set_color(0x0F);
    terminal_write_key_value("heap bytes used", memory_heap_used());
    terminal_write_key_value("pages used", memory_pages_used());
    terminal_write_key_value("pages total", memory_pages_total());
    terminal_write_key_value("paging enabled", paging_enabled());
    terminal_write_key_value("mapped mb", paging_mapped_megabytes());
}

static void show_ramfs_report(void) {
    size_t file_count = ramfs_file_count();

    terminal_set_color(0x0D);
    terminal_writeln("");
    terminal_writeln("[ramfs]");
    terminal_set_color(0x0F);
    terminal_write_key_value("files", file_count);

    for (size_t i = 0; i < file_count; ++i) {
        const ramfs_file_t* file = ramfs_get_at(i);
        if (!file) {
            continue;
        }
        terminal_write(" - ");
        terminal_write(file->name);
        terminal_write(" (");
        terminal_write_dec(file->size);
        terminal_writeln(" bytes)");
    }
}

static void show_tinyfs_report(void) {
    size_t file_count = tinyfs_file_count();

    terminal_set_color(0x09);
    terminal_writeln("");
    terminal_writeln("[tinyfs]");
    terminal_set_color(0x0F);
    terminal_write_key_value("files", file_count);

    for (size_t i = 0; i < file_count; ++i) {
        const tinyfs_file_t* file = tinyfs_get_at(i);
        if (!file) {
            continue;
        }
        terminal_write(" - ");
        terminal_write(file->name);
        terminal_write(" (");
        terminal_write_dec(file->size);
        terminal_write(" bytes, block ");
        terminal_write_dec(file->block_index);
        terminal_writeln(")");
    }
}

static void show_process_report(void) {
    terminal_set_color(0x0A);
    terminal_writeln("");
    terminal_writeln("[processes]");
    terminal_set_color(0x0F);
    terminal_write_key_value("known slots", scheduler_process_count());
    terminal_write_key_value("ring3 prepared", scheduler_ring3_ready_count());
    terminal_write_key_value("ring3 active", scheduler_ring3_active());
    terminal_write_key_value("ticks", scheduler_ticks());
    terminal_write_key_value("current index", scheduler_current_index());

    for (size_t i = 0; i < PROCESS_SLOTS; ++i) {
        const process_t* process = scheduler_get_process(i);
        if (!process) {
            continue;
        }
        terminal_write(" - pid=");
        terminal_write_dec(process->pid);
        terminal_write(" ");
        terminal_write(process->name ? process->name : "unnamed");
        terminal_write(" priv=");
        terminal_write(process->privilege == PROCESS_PRIVILEGE_USER ? "user" : "kernel");
        terminal_write(" runs=");
        terminal_write_dec(process->runs);
        terminal_write(" slice=");
        terminal_write_dec(process->time_slice);
        terminal_writeln("");
        terminal_write("   entry=");
        terminal_write_hex((uint32_t)process->entry_point);
        terminal_write(" kstack=");
        terminal_write_hex((uint32_t)process->kernel_stack_top);
        if (process->privilege == PROCESS_PRIVILEGE_USER) {
            terminal_write(" ustack=");
            terminal_write_hex((uint32_t)process->user_stack_top);
            terminal_write(" ring3=");
            terminal_write(process->ring3_ready ? "prepared" : "missing");
        }
        terminal_writeln("");
    }
}

static void show_system_report(void) {
    terminal_set_color(0x0C);
    terminal_writeln("");
    terminal_writeln("[system]");
    terminal_set_color(0x0F);
    terminal_write_key_value("pit hz", timer_frequency());
    terminal_write_key_value("pit ticks", timer_ticks());
    terminal_write_key_value("keyboard buffered", keyboard_pending());
    terminal_write_key_value("ramdisk blocks", block_device_capacity());
    terminal_write_key_value("syscalls", syscall_count());
    terminal_write_key_value("user descriptors ready", gdt_user_mode_ready());
    terminal_write_key_value("paging enabled", paging_enabled());
    terminal_write_key_value("mapped megabytes", paging_mapped_megabytes());
    terminal_write_key_value("tss ready", gdt_tss_ready());
    terminal_write("kernel esp0: ");
    terminal_write_hex(gdt_kernel_stack_top());
    terminal_writeln("");
}

void kernel_main(void) {
    static process_context_t kernel_runtime_log = {
        "var/log/boot.runtime",
        "runtime kernel maintenance pass",
        2,
        0
    };
    static probe_context_t user_probe = {
        0
    };
    static shell_context_t user_shell = {
        0,
        0,
        0,
        {0}
    };
    static shell_probe_context_t shell_probe = {
        0
    };
    static fs_stress_context_t fs_stress = {
        0
    };

    debug_port_writeln("ToyOS: kernel_main entered");
    terminal_initialize();
    draw_status_box();
    gdt_initialize();
    if (!gdt_user_mode_ready() || !gdt_tss_ready()) {
        panic("descriptor or tss initialization failed");
    }
    debug_port_writeln("ToyOS: GDT and TSS ready");
    idt_initialize();
    syscall_initialize();
    memory_initialize();
    vfs_initialize();
    scheduler_initialize();
    block_device_initialize();
    timer_initialize(100);
    keyboard_initialize();
    debug_port_writeln("ToyOS: core subsystems initialized");

    if (!kmalloc(256) || !kmalloc(512)) {
        panic("kernel heap allocation failed");
    }
    void* page_a = page_alloc();
    void* page_b = page_alloc();
    void* kernel_irq_stack = page_alloc();
    if (!page_a || !page_b || !kernel_irq_stack) {
        panic("page allocation failed");
    }
    gdt_set_kernel_stack((uint32_t)(uintptr_t)kernel_irq_stack + 4096u);
    debug_port_writeln("ToyOS: memory allocations ready");
    maybe_run_paging_stage1_smoke();

    if (tinyfs_format() != 0 || tinyfs_mount() != 0) {
        panic("tinyfs initialization failed");
    }
    if (tinyfs_write_text("etc/motd", "Welcome to ToyOS TinyFS.") != 0) {
        panic("failed to write TinyFS motd");
    }
    if (tinyfs_write_text("usr/readme.txt", "Syscall gate, TSS, and ring3 stack scaffolding online.") != 0) {
        panic("failed to write TinyFS readme");
    }
    if (tinyfs_write_text("var/log/boot.log", "boot: tinyfs + syscall + tss layer initialized") != 0) {
        panic("failed to write TinyFS boot log");
    }
    if (ramfs_write_text("proc/meminfo", "heap and pages initialized") != 0) {
        panic("failed to write RAMFS meminfo");
    }
    if (ramfs_write_text("proc/drivers", "pit keyboard ramdisk syscall online") != 0) {
        panic("failed to write RAMFS driver report");
    }
    if (ramfs_write_text("proc/ring3", "user stacks prepared; iret handoff and syscall path online; paging kept experimental") != 0) {
        panic("failed to write RAMFS ring3 report");
    }
    if (ramfs_write_text("tmp/session", "temporary runtime workspace") != 0) {
        panic("failed to write RAMFS tmp session");
    }

    debug_port_writeln("ToyOS: filesystems ready");

    if (scheduler_create_process("kernel-maint", kernel_fs_process, &kernel_runtime_log, PROCESS_PRIVILEGE_KERNEL, 2, 2) == 0) {
        panic("failed to create kernel maintenance process");
    }
    if (scheduler_create_process("fs-stress", kernel_fs_stress_process, &fs_stress, PROCESS_PRIVILEGE_KERNEL, 2, 1) == 0) {
        panic("failed to create filesystem stress process");
    }
    if (scheduler_create_process("fs-writer-a", kernel_fs_multi_writer_process, &fs_writer_a_ctx, PROCESS_PRIVILEGE_KERNEL, 2, 1) == 0) {
        panic("failed to create filesystem writer A");
    }
    if (scheduler_create_process("fs-writer-b", kernel_fs_multi_writer_process, &fs_writer_b_ctx, PROCESS_PRIVILEGE_KERNEL, 2, 1) == 0) {
        panic("failed to create filesystem writer B");
    }
    if (scheduler_create_process("fs-multi-verify", kernel_fs_multi_verify_process, &fs_multi_verify_ctx, PROCESS_PRIVILEGE_KERNEL, 1, 1) == 0) {
        panic("failed to create filesystem multi verify process");
    }
    if (scheduler_create_process("user-probe", toy_user_probe_process, &user_probe, PROCESS_PRIVILEGE_USER, 2, 1) == 0) {
        panic("failed to create user probe process");
    }
    if (scheduler_create_process("user-shell", toy_user_shell_process, &user_shell, PROCESS_PRIVILEGE_USER, 1, 1) == 0) {
        panic("failed to create user shell process");
    }
    if (scheduler_create_process("shell-probe", toy_user_shell_probe_process, &shell_probe, PROCESS_PRIVILEGE_USER, 2, 1) == 0) {
        panic("failed to create shell probe process");
    }
    if (scheduler_create_process("fs-mixed-probe", toy_user_fs_mixed_probe_process, &fs_mixed_probe_ctx, PROCESS_PRIVILEGE_USER, 2, 1) == 0) {
        panic("failed to create filesystem mixed probe process");
    }
    debug_port_writeln("ToyOS: processes created");

    scheduler_run_rounds(6);
    debug_port_writeln("ToyOS: scheduler rounds completed");

    show_memory_report();
    terminal_write("page A: ");
    terminal_write_hex((uint32_t)(uintptr_t)page_a);
    terminal_writeln("");
    terminal_write("page B: ");
    terminal_write_hex((uint32_t)(uintptr_t)page_b);
    terminal_writeln("");
    terminal_write("kernel irq stack top: ");
    terminal_write_hex((uint32_t)(uintptr_t)kernel_irq_stack + 4096u);
    terminal_writeln("");

    show_ramfs_report();
    show_tinyfs_report();
    show_process_report();
    show_system_report();

    terminal_set_color(0x0E);
    terminal_writeln("");
    terminal_writeln("Triggering a software interrupt test...");
    __asm__ __volatile__("int $0x30");

    terminal_set_color(0x0A);
    terminal_writeln("ToyOS kernel services are online.");
    debug_port_writeln("ToyOS: kernel services online");

    for (;;) {
        __asm__ __volatile__("hlt");
    }
}
