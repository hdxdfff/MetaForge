#include "security.h"

static toyos_tls_state_t g_tls_state = TOYOS_TLS_STATE_IDLE;

void toy_tls_initialize(void) {
    g_tls_state = TOYOS_TLS_STATE_IDLE;
}

void toy_tls_session_initialize(toyos_tls_session_t* session) {
    size_t i;

    if (!session) {
        return;
    }

    for (i = 0; i < sizeof(session->session_id); ++i) {
        session->session_id[i] = (uint8_t)(0xA0u + i);
    }
    for (i = 0; i < sizeof(session->key); ++i) {
        session->key[i] = 0;
    }
    session->nonce = 0;
    session->created_at = 0;
    session->expires_at = 0;
    session->established = 0;
}

void toy_security_initialize(void) {
    toy_tls_initialize();
    toy_rpc_initialize();
    toy_keystore_initialize();
    toy_security_monitor_initialize();
}

void toy_security_tick(uint64_t now_ticks) {
    (void)now_ticks;
    if (g_tls_state == TOYOS_TLS_STATE_ESTABLISHED) {
        return;
    }
}
