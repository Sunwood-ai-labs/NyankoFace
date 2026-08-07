---
title: GPU workers
type: guide
description: Public contracts for optional GPU-backed Space execution.
readingTime: 5 min
tags: [gpu, spaces, runtime, security]
related:
  - title: Docker Spaces
    link: /guide/spaces
  - title: Space Variables and Secrets
    link: /guide/space-environment
---

# GPU workers

NyankoFace can run Dockerfile-based Spaces on an optional GPU worker. The
worker polls for an authenticated lease, builds the requested revision, and
returns a short-lived runtime URL. CPU execution remains the default path.

## Public-safe default

The example worker is deliberately ordinary: it starts jobs with the normal
container boundary and has no trusted repository list. The checked-in
[`runtime-profile.example.json`](../../gpu-worker/runtime-profile.example.json)
therefore cannot enable host integration by itself.

The compose example uses only placeholders and loopback binding. Replace the
connection settings through a private deployment overlay or secret store; do
not commit organization hostnames, addresses, credentials, or hardware
inventory.

## Optional private runtime profile

A private operator may mount a separate JSON profile at the path configured by
`WORKER_RUNTIME_PROFILE_FILE`:

```json
{
  "repositories": ["owner/diagnostics-space"],
  "share_namespaces": true,
  "metadata_mount": {
    "source": "/private/metadata",
    "target": "/runtime/metadata",
    "read_only": true
  }
}
```

The worker enables the additional Docker options only when all of these are
true:

- the repository slug is explicitly listed;
- namespace sharing is explicitly enabled;
- the metadata mount has absolute paths and `read_only: true`.

Missing, malformed, unlisted, or writable settings fail closed to ordinary
container execution. Keep the real profile outside the public repository. The
source path above is an example placeholder, not a deployment value.

## Operational boundary

Host-integrated diagnostics are a privileged deployment capability. Limit the
allowlist to repositories that have been reviewed, use a read-only mount, and
keep worker enrollment credentials outside Git. The public repository contains
the policy contract and tests, not private topology or live runtime evidence.
