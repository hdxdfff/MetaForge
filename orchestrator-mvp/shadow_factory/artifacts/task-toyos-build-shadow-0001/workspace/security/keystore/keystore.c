#include "security.h"

#define TOYOS_IDENTITY_STORE_CAPACITY 8u

static toyos_node_identity_t g_identity_store[TOYOS_IDENTITY_STORE_CAPACITY];
static uint8_t g_identity_store_used[TOYOS_IDENTITY_STORE_CAPACITY];

static int toy_identity_matches(const uint8_t* left, const uint8_t* right, size_t size) {
    size_t i;
    for (i = 0; i < size; ++i) {
        if (left[i] != right[i]) {
            return 0;
        }
    }
    return 1;
}

void toy_keystore_initialize(void) {
    size_t i;
    for (i = 0; i < TOYOS_IDENTITY_STORE_CAPACITY; ++i) {
        g_identity_store_used[i] = 0u;
    }
}

toyos_security_status_t toy_keystore_store_certificate(
    const toyos_node_identity_t* identity) {
    size_t i;

    if (!identity) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    for (i = 0; i < TOYOS_IDENTITY_STORE_CAPACITY; ++i) {
        if (!g_identity_store_used[i]) {
            g_identity_store[i] = *identity;
            g_identity_store_used[i] = 1u;
            return TOYOS_SECURITY_STATUS_OK;
        }
    }
    return TOYOS_SECURITY_STATUS_FULL;
}

toyos_security_status_t toy_keystore_get_certificate(
    const uint8_t* node_id,
    toyos_node_identity_t* identity_out) {
    size_t i;

    if (!node_id || !identity_out) {
        return TOYOS_SECURITY_STATUS_INVALID;
    }

    for (i = 0; i < TOYOS_IDENTITY_STORE_CAPACITY; ++i) {
        if (g_identity_store_used[i] &&
            toy_identity_matches(g_identity_store[i].node_id, node_id, sizeof(g_identity_store[i].node_id))) {
            *identity_out = g_identity_store[i];
            return TOYOS_SECURITY_STATUS_OK;
        }
    }

    return TOYOS_SECURITY_STATUS_EMPTY;
}
