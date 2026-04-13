#ifndef SECURITY_H
#define SECURITY_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    TOYOS_SECURITY_STATUS_OK = 0,
    TOYOS_SECURITY_STATUS_INVALID = 1,
    TOYOS_SECURITY_STATUS_UNSUPPORTED = 2,
    TOYOS_SECURITY_STATUS_FULL = 3,
    TOYOS_SECURITY_STATUS_EMPTY = 4,
    TOYOS_SECURITY_STATUS_EXPIRED = 5,
    TOYOS_SECURITY_STATUS_DENIED = 6,
} toyos_security_status_t;

typedef enum {
    TOYOS_TLS_RECORD_INVALID = 0,
    TOYOS_TLS_RECORD_CHANGE_CIPHER_SPEC = 20,
    TOYOS_TLS_RECORD_ALERT = 21,
    TOYOS_TLS_RECORD_HANDSHAKE = 22,
    TOYOS_TLS_RECORD_APPLICATION_DATA = 23,
} toyos_tls_record_type_t;

typedef enum {
    TOYOS_TLS_HANDSHAKE_CLIENT_HELLO = 1,
    TOYOS_TLS_HANDSHAKE_SERVER_HELLO = 2,
    TOYOS_TLS_HANDSHAKE_ENCRYPTED_EXTENSIONS = 8,
    TOYOS_TLS_HANDSHAKE_CERTIFICATE = 11,
    TOYOS_TLS_HANDSHAKE_CERTIFICATE_VERIFY = 15,
    TOYOS_TLS_HANDSHAKE_FINISHED = 20,
} toyos_tls_handshake_type_t;

typedef enum {
    TOYOS_TLS_STATE_IDLE = 0,
    TOYOS_TLS_STATE_CLIENT_HELLO_SENT = 1,
    TOYOS_TLS_STATE_SERVER_HELLO_RECEIVED = 2,
    TOYOS_TLS_STATE_KEYS_DERIVED = 3,
    TOYOS_TLS_STATE_ESTABLISHED = 4,
    TOYOS_TLS_STATE_CLOSED = 5,
} toyos_tls_state_t;

typedef enum {
    TOYOS_RPC_METHOD_NONE = 0,
    TOYOS_RPC_METHOD_PING = 1,
    TOYOS_RPC_METHOD_NODE_ATTEST = 2,
    TOYOS_RPC_METHOD_KEY_ROTATE = 3,
    TOYOS_RPC_METHOD_SECURITY_STATUS = 4,
} toyos_rpc_method_id_t;

typedef enum {
    TOYOS_MONITOR_EVENT_NONE = 0,
    TOYOS_MONITOR_EVENT_TLS_ERROR = 1,
    TOYOS_MONITOR_EVENT_FAILED_AUTH = 2,
    TOYOS_MONITOR_EVENT_CERT_MISMATCH = 3,
    TOYOS_MONITOR_EVENT_DOS_ATTEMPT = 4,
    TOYOS_MONITOR_EVENT_REPLAY_DROP = 5,
} toyos_monitor_event_type_t;

typedef struct {
    uint8_t type;
    uint16_t legacy_version;
    uint16_t length;
    uint8_t payload[512];
} toyos_tls_record_t;

typedef struct {
    uint8_t session_id[32];
    uint8_t key[32];
    uint64_t nonce;
    uint64_t created_at;
    uint64_t expires_at;
    uint8_t established;
} toyos_tls_session_t;

typedef struct {
    uint8_t node_id[32];
    uint8_t public_key[32];
    uint8_t certificate[256];
    uint16_t certificate_length;
} toyos_node_identity_t;

typedef struct {
    uint32_t magic;
    uint32_t method_id;
    uint32_t payload_len;
    uint8_t payload[256];
} toyos_rpc_packet_t;

typedef struct {
    uint64_t nonce;
    uint64_t timestamp;
    toyos_monitor_event_type_t last_event;
    uint32_t dropped_replays;
    uint32_t failed_auths;
    uint32_t tls_errors;
} toyos_security_monitor_t;

void toy_security_initialize(void);
void toy_security_tick(uint64_t now_ticks);

void toy_tls_initialize(void);
void toy_tls_session_initialize(toyos_tls_session_t* session);
void toy_tls_record_initialize(toyos_tls_record_t* record, uint8_t type);
toyos_security_status_t toy_tls_build_client_hello(
    toyos_tls_session_t* session,
    toyos_tls_record_t* record,
    uint8_t* out,
    size_t out_capacity,
    size_t* out_size);
toyos_security_status_t toy_tls_process_server_hello(
    toyos_tls_session_t* session,
    const uint8_t* input,
    size_t input_size);
toyos_security_status_t toy_tls_encrypt_record(
    toyos_tls_session_t* session,
    toyos_tls_record_t* record,
    uint8_t* out,
    size_t out_capacity,
    size_t* out_size);
toyos_security_status_t toy_tls_decrypt_record(
    toyos_tls_session_t* session,
    const uint8_t* input,
    size_t input_size,
    toyos_tls_record_t* record);
void toy_tls_mock_hkdf(
    const uint8_t* shared_secret,
    size_t shared_secret_size,
    uint8_t* out_key,
    size_t out_size);

void toy_rpc_initialize(void);
void toy_rpc_register(uint32_t method_id);
toyos_security_status_t toy_rpc_call(
    toyos_tls_session_t* session,
    uint32_t method_id,
    const uint8_t* payload,
    size_t payload_size,
    toyos_rpc_packet_t* response);
toyos_security_status_t toy_rpc_dispatch(
    const toyos_rpc_packet_t* request,
    toyos_rpc_packet_t* response);

void toy_keystore_initialize(void);
toyos_security_status_t toy_keystore_store_certificate(
    const toyos_node_identity_t* identity);
toyos_security_status_t toy_keystore_get_certificate(
    const uint8_t* node_id,
    toyos_node_identity_t* identity_out);
toyos_security_status_t toy_keystore_store_session(
    const toyos_tls_session_t* session);
toyos_security_status_t toy_keystore_get_session(
    const uint8_t* session_id,
    toyos_tls_session_t* session_out);

void toy_security_monitor_initialize(void);
void toy_security_monitor_record(toyos_monitor_event_type_t event_type);
const toyos_security_monitor_t* toy_security_monitor_snapshot(void);

#endif
