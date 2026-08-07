---
title: Runtime Environment Receipt
emoji: 🔐
colorFrom: slate
colorTo: cyan
sdk: docker
license: apache-2.0
---

# Runtime Environment Receipt

A CPU-only FastAPI Space that proves NyankoFace runtime Variables and Secrets are
available inside the launched container.

## Configure it in NyankoFace

Open **Variables & Secrets** on this Space and add:

| Name | Type | Example | Used for |
| --- | --- | --- | --- |
| `DEMO_HEADLINE` | Variable | `Configured by NyankoFace` | Main page headline |
| `DEMO_REGION` | Variable | `tokyo-lab-01` | Runtime location |
| `DEMO_ACCENT` | Variable | `#42f5c5` | Interface accent color |
| `DEMO_API_TOKEN` | Secret | any non-production demo value | HMAC-signing runtime receipts |

Restart the Space after saving the values. The app displays Variables, but it
never returns the Secret. Instead, the backend uses `DEMO_API_TOKEN` to produce
an HMAC-SHA256 signature and shows only a short one-way fingerprint.

Do not use a real credential in this sample.
