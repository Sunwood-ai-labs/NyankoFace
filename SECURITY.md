# Security policy

## Supported versions

NyankoFace is currently developed on the `main` branch. Security fixes are applied to the latest revision; no older release line is maintained yet.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability reporting for this repository when available, or contact the maintainers through the Sunwood AI Labs organization profile.

Include the affected revision, deployment model, reproduction steps, impact, and any suggested mitigation. Please avoid accessing data that is not yours while validating a report.

## Deployment boundary

NyankoFace is designed for trusted local or private-network use. The Space runner mounts the host Docker socket and can build and run repository-provided Dockerfiles. That capability is equivalent to strong control over the Docker host.

- Keep self-registration disabled unless the host is isolated for untrusted workloads.
- Do not expose a default-password deployment to the public internet.
- Replace the bootstrap password on first use.
- Use a trusted TLS certificate for shared or public deployments.
- Review imported repositories and Dockerfiles before running them.
- Back up Forgejo and agent-metrics volumes before upgrades.

NyankoFace is not a hardened multi-tenant sandbox.
