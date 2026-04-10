#include "security.h"

static toyos_security_monitor_t g_monitor;

void toy_security_monitor_initialize(void) {
    g_monitor.nonce = 0;
    g_monitor.timestamp = 0;
    g_monitor.last_event = TOYOS_MONITOR_EVENT_NONE;
    g_monitor.dropped_replays = 0;
    g_monitor.failed_auths = 0;
    g_monitor.tls_errors = 0;
}

void toy_security_monitor_record(toyos_monitor_event_type_t event_type) {
    g_monitor.last_event = event_type;
    if (event_type == TOYOS_MONITOR_EVENT_REPLAY_DROP) {
        g_monitor.dropped_replays += 1u;
    } else if (event_type == TOYOS_MONITOR_EVENT_FAILED_AUTH ||
               event_type == TOYOS_MONITOR_EVENT_CERT_MISMATCH) {
        g_monitor.failed_auths += 1u;
    } else if (event_type == TOYOS_MONITOR_EVENT_TLS_ERROR) {
        g_monitor.tls_errors += 1u;
    }
}

const toyos_security_monitor_t* toy_security_monitor_snapshot(void) {
    return &g_monitor;
}
