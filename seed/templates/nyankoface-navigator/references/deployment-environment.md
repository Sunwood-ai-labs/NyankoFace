# NyankoFace public deployment safety

This public snapshot intentionally omits private hostnames, network addresses,
hardware topology, host-namespace settings, and environment-specific endpoints.

Use `.env.example` as the starting point for a local deployment. Put credentials,
tokens, certificates, and provider keys in an untracked secret store or local
secret file. Replace all bootstrap values before sharing a running instance.

Before publishing diagnostics, remove hostnames, addresses, internal URLs,
screenshots of private dashboards, and logs that contain identifiers. Keep
deployment backups and database exports outside Git.

The application source documents public contracts only; private deployment
procedures belong in an access-controlled runbook outside this repository.
