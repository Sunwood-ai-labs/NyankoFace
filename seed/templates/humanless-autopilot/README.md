# PulseBoard

PulseBoard is a local-first status and incident timeline for small teams. This
repository is intentionally limited to a product brief: NyankoFace humanless mode
must design, implement, test, document, independently review, and maintain the
working product without waiting for a human-authored Issue.

## Product brief

Teams need a fast way to record service status updates during an incident
without provisioning a database or sending operational notes to a third party.
The product should run locally in Docker and remain useful on both phones and
desktop browsers.

## Required first release

- Create, edit, and delete timestamped status entries.
- Record the affected service, severity, current state, and a short update.
- Filter the timeline by service and severity.
- Persist data locally in the browser.
- Export and import a portable JSON backup.
- Provide an accessible responsive interface in Japanese.
- Include tests, a Dockerfile, healthcheck guidance, and reconstruction steps.

The autonomous maintainer may choose the implementation stack. It must verify
the real application instead of treating placeholder markup as complete.
