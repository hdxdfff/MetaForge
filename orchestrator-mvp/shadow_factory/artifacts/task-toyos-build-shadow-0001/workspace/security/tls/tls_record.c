#include "security.h"

void toy_tls_record_initialize(toyos_tls_record_t* record, uint8_t type) {
    size_t i;

    if (!record) {
        return;
    }

    record->type = type;
    record->legacy_version = 0x0303u;
    record->length = 0;
    for (i = 0; i < sizeof(record->payload); ++i) {
        record->payload[i] = 0;
    }
}

toyos_security_status_t toy_tls_encrypt_record(
    toyos_tls_session_t* session,
    toyos_tls_record_t* record,
    uint8_t* out,
    size_t out_capacity,
    size_t* out_size) {
    size_t total_size;
    size_t i;

    if (!session || !record || !out || !out_size) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    total_size = (size_t)record->length + 5u;
    if (out_capacity < total_size) {
        return TOYOS_SECURITY_STATUS_FULL;
    }

    out[0] = record->type;
    out[1] = (uint8_t)(record->legacy_version >> 8);
    out[2] = (uint8_t)(record->legacy_version & 0xFFu);
    out[3] = (uint8_t)(record->length >> 8);
    out[4] = (uint8_t)(record->length & 0xFFu);
    for (i = 0; i < (size_t)record->length; ++i) {
        out[5u + i] = (uint8_t)(record->payload[i] ^ session->key[i % sizeof(session->key)] ^ (uint8_t)session->nonce);
    }
    session->nonce += 1u;
    *out_size = total_size;
    return TOYOS_SECURITY_STATUS_OK;
}

toyos_security_status_t toy_tls_decrypt_record(
    toyos_tls_session_t* session,
    const uint8_t* input,
    size_t input_size,
    toyos_tls_record_t* record) {
    size_t payload_size;
    size_t i;

    if (!session || !input || !record || input_size < 5u) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    payload_size = ((size_t)input[3] << 8) | (size_t)input[4];
    if (input_size < payload_size + 5u || payload_size > sizeof(record->payload)) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    record->type = input[0];
    record->legacy_version = (uint16_t)(((uint16_t)input[1] << 8) | input[2]);
    record->length = (uint16_t)payload_size;
    for (i = 0; i < payload_size; ++i) {
        record->payload[i] = (uint8_t)(input[5u + i] ^ session->key[i % sizeof(session->key)] ^ (uint8_t)session->nonce);
    }
    session->nonce += 1u;
    return TOYOS_SECURITY_STATUS_OK;
}
