# NyankoFace public deployment safety

This starter intentionally omits private hostnames, network addresses, hardware
topology, host-namespace settings, and environment-specific endpoints.

Use the repository's `.env.example` as a local starting point. Keep credentials,
tokens, certificates, and provider keys in untracked secret storage. Before
sharing diagnostics, remove hostnames, addresses, internal URLs, and private
screenshots.

Deployment backups and database exports belong outside Git. Private deployment
procedures should live in an access-controlled runbook, not in this starter.
