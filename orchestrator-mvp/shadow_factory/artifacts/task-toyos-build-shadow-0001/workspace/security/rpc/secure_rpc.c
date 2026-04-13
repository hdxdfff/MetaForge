#include "security.h"

#define TOYOS_RPC_MAGIC 0x54595250u
#define TOYOS_RPC_METHOD_CAPACITY 16u

static uint32_t g_rpc_methods[TOYOS_RPC_METHOD_CAPACITY];
static size_t g_rpc_method_count = 0;

void toy_rpc_initialize(void) {
    g_rpc_method_count = 0;
}

void toy_rpc_register(uint32_t method_id) {
    if (g_rpc_method_count >= TOYOS_RPC_METHOD_CAPACITY) {
        return;
    }
    g_rpc_methods[g_rpc_method_count++] = method_id;
}

toyos_security_status_t toy_rpc_dispatch(
    const toyos_rpc_packet_t* request,
    toyos_rpc_packet_t* response) {
    if (!request || !response) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }
    if (request->magic != TOYOS_RPC_MAGIC) {
        toy_security_monitor_record(TOYOS_MONITOR_EVENT_FAILED_AUTH);
        return TOYOS_SECURITY_STATUS_DENIED;
    }

    response->magic = TOYOS_RPC_MAGIC;
    response->method_id = request->method_id;
    response->payload_len = 2u;
    response->payload[0] = 'O';
    response->payload[1] = 'K';
    return TOYOS_SECURITY_STATUS_OK;
}

toyos_security_status_t toy_rpc_call(
    toyos_tls_session_t* session,
    uint32_t method_id,
    const uint8_t* payload,
    size_t payload_size,
    toyos_rpc_packet_t* response) {
    toyos_rpc_packet_t request;
    size_t i;

    if (!session || !response) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }
    if (!session->established) {
        return TOYOS_SECURITY_STATUS_DENIED;
    }
    if (payload_size > sizeof(request.payload)) {
        return TOYOS_SECURITY_STATUS_FULL;
    }

    request.magic = TOYOS_RPC_MAGIC;
    request.method_id = method_id;
    request.payload_len = (uint32_t)payload_size;
    for (i = 0; i < payload_size; ++i) {
        request.payload[i] = payload ? payload[i] : 0;
    }
    return toy_rpc_dispatch(&request, response);
}
