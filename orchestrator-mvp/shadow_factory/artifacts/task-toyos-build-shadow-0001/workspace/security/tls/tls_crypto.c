#include "security.h"

static void toy_tls_derive_material(const uint8_t* seed, size_t seed_size, uint8_t* out, size_t out_size) {
    size_t i;
    uint8_t rolling = 0x5Cu;

    for (i = 0; i < out_size; ++i) {
        rolling = (uint8_t)(rolling + seed[i % seed_size] + (uint8_t)i);
        out[i] = (uint8_t)(rolling ^ 0xA5u);
    }
}

void toy_tls_mock_hkdf(const uint8_t* shared_secret, size_t shared_secret_size, uint8_t* out_key, size_t out_size) {
    if (!shared_secret || shared_secret_size == 0 || !out_key || out_size == 0) {
        return;
    }
    toy_tls_derive_material(shared_secret, shared_secret_size, out_key, out_size);
}
