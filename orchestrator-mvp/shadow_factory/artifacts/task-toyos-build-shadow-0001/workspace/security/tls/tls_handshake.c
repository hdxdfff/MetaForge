#include "security.h"

static void toy_tls_fill_bytes(uint8_t* out, size_t size, uint8_t seed) {
    size_t i;
    for (i = 0; i < size; ++i) {
        out[i] = (uint8_t)(seed + (uint8_t)(i * 7u));
    }
}

toyos_security_status_t toy_tls_build_client_hello(
    toyos_tls_session_t* session,
    toyos_tls_record_t* record,
    uint8_t* out,
    size_t out_capacity,
    size_t* out_size) {
    if (!session || !record || !out || !out_size) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    toy_tls_record_initialize(record, TOYOS_TLS_RECORD_HANDSHAKE);
    record->payload[0] = TOYOS_TLS_HANDSHAKE_CLIENT_HELLO;
    toy_tls_fill_bytes(&record->payload[1], 32u, 0x11u);
    record->length = 33u;
    return toy_tls_encrypt_record(session, record, out, out_capacity, out_size);
}

toyos_security_status_t toy_tls_process_server_hello(
    toyos_tls_session_t* session,
    const uint8_t* input,
    size_t input_size) {
    toyos_tls_record_t record;
    size_t i;

    if (!session || !input) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }
    if (toy_tls_decrypt_record(session, input, input_size, &record) != TOYOS_SECURITY_STATUS_OK) {
        toy_security_monitor_record(TOYOS_MONITOR_EVENT_TLS_ERROR);
        return TOYOS_SECURITY_STATUS_INVALID;
    }
    if (record.type != TOYOS_TLS_RECORD_HANDSHAKE || record.length < 33u ||
        record.payload[0] != TOYOS_TLS_HANDSHAKE_SERVER_HELLO) {
        toy_security_monitor_record(TOYOS_MONITOR_EVENT_TLS_ERROR);
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    for (i = 0; i < sizeof(session->key); ++i) {
        session->key[i] = (uint8_t)(record.payload[1u + (i % 32u)] ^ session->session_id[i]);
    }
    session->established = 1u;
    return TOYOS_SECURITY_STATUS_OK;
}
