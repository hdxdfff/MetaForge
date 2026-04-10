#include "security.h"

#define TOYOS_TLS_SESSION_TABLE_CAPACITY 8u

static toyos_tls_session_t g_tls_sessions[TOYOS_TLS_SESSION_TABLE_CAPACITY];
static uint8_t g_tls_sessions_used[TOYOS_TLS_SESSION_TABLE_CAPACITY];

static int toy_tls_session_matches(const uint8_t* left, const uint8_t* right, size_t size) {
    size_t i;
    for (i = 0; i < size; ++i) {
        if (left[i] != right[i]) {
            return 0;
        }
    }
    return 1;
}

toyos_security_status_t toy_keystore_store_session(
    const toyos_tls_session_t* session) {
    size_t i;

    if (!session) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    for (i = 0; i < TOYOS_TLS_SESSION_TABLE_CAPACITY; ++i) {
        if (!g_tls_sessions_used[i]) {
            g_tls_sessions[i] = *session;
            g_tls_sessions_used[i] = 1u;
            return TOYOS_SECURITY_STATUS_OK;
        }
    }

    return TOYOS_SECURITY_STATUS_FULL;
}

toyos_security_status_t toy_keystore_get_session(
    const uint8_t* session_id,
    toyos_tls_session_t* session_out) {
    size_t i;

    if (!session_id || !session_out) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    for (i = 0; i < TOYOS_TLS_SESSION_TABLE_CAPACITY; ++i) {
        if (g_tls_sessions_used[i] &&
            toy_tls_session_matches(g_tls_sessions[i].session_id, session_id, sizeof(g_tls_sessions[i].session_id))) {
            *session_out = g_tls_sessions[i];
            return TOYOS_SECURITY_STATUS_OK;
        }
    }

    return TOYOS_SECURITY_STATUS_EMPTY;
}
