# ToyOS Security Network Architecture

## Goal

This artifact defines a realistic path for adding a secure network subsystem to the current ToyOS teaching kernel without pretending that TLS can exist before transport, identity, and key storage are present.

## Current baseline

ToyOS currently has:

- process scheduling
- syscall entry
- in-memory and block-backed filesystems
- timer and keyboard IRQ support
- no TCP/IP stack
- no socket abstraction
- no certificate or key lifecycle

That means the security-network effort must be staged.

## Target stack

```text
Application
   |
Secure RPC
   |
TLS 1.3 / mTLS profile
   |
Transport abstraction
   |
TCP / UDP
   |
IP
   |
NIC driver
```

## Module layout

```text
include/security.h
security/
  tls/
    tls.c
    tls_handshake.c
    tls_record.c
    tls_crypto.c
    tls_session.c
  rpc/
    secure_rpc.c
  keystore/
    keystore.c
  monitor/
    security_monitor.c
```

## Design rules

1. TLS stays a subsystem, not a transport replacement.
2. Secure RPC depends on TLS session state rather than bypassing it.
3. Node identity is certificate-backed and suitable for mTLS later.
4. Replay resistance uses nonce plus timestamp, but transport ordering still matters.
5. Keystore and monitor are shared services, not RPC-local state.

## Staged delivery

### Stage 0: scaffold

- define types, interfaces, and state containers
- compile the subsystem without integrating into boot flow
- document what is placeholder logic versus real cryptography

### Stage 1: transport abstraction

- add kernel socket-like send/receive interface
- define framed byte-stream contract used by TLS record layer
- create loopback test path before real NIC work

### Stage 2: identity and keystore

- add node identity generation
- store certificate material in memory-only tables
- add expiration and rotation policies

### Stage 3: TLS handshake core

- replace placeholder key derivation with real ECDHE + HKDF
- add transcript hash and Finished verification
- support session resume policy only after full handshake correctness

### Stage 4: Secure RPC

- enforce RPC over established TLS only
- add method registry, dispatch, authz hooks, and replay checks
- define machine-readable method IDs for AI node coordination

### Stage 5: Zero Trust profile

- require mTLS on node-to-node links
- bind node identity to `node_id = SHA256(pubkey)`
- reject unauthenticated peers by default

### Stage 6: update and monitoring

- add signed update package verification
- persist security events into kernel-visible telemetry surfaces
- surface failed auth, cert mismatch, replay drop, and DoS counters

## What the new code does now

- `security.h` exposes the subsystem contract
- TLS record and handshake files provide compile-safe placeholder flows
- Secure RPC enforces an established-session precondition
- keystore stores node identities and cached sessions in bounded in-memory tables
- monitor records security event counters for future policy enforcement

## What it does not do yet

- real AES-GCM
- real HKDF
- real ECDHE
- real certificates
- real TCP/IP networking
- actual mTLS validation

## Next automatic work items

1. Introduce a transport facade under `include/net.h` and `src/net.c`.
2. Build a loopback-only packet path to exercise TLS records without NIC complexity.
3. Add a kernel self-test that creates a fake client/server handshake and RPC ping.
4. Expand `build-report.json` or a dedicated security report with subsystem coverage.
