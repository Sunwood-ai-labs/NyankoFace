# NyankoFace issue report contract

The report contract is intentionally small. The agent-side command writes one
JSON envelope to `outbox/pending/<report_id>.json`; the operator-side command
publishes its already-rendered `markdown` field.

## Required envelope fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer contract version, currently `1` |
| `report_id` | First 20 hexadecimal characters of the stable fingerprint |
| `fingerprint` | SHA-256 of the normalized report content, excluding timestamps and identity |
| `status` | `pending` or `published` |
| `report_kind` | `bug` or `enhancement` |
| `title` | Bounded Issue title after redaction |
| `reporter` | Lowercase agent slug |
| `source` | Public-safe observation source after redaction |
| `observed_at` | UTC ISO-8601 observation time |
| `staged_at` | UTC ISO-8601 outbox time |
| `report` | Structured fields listed below |
| `markdown` | Deterministic GitHub Issue body |
| `dedupe_query` | Safe title query for the operator's open-Issue search |
| `redactions_applied` | Count of substitutions performed before writing |

`report` contains `summary`, `environment`, `reproduction_steps`, `expected`,
`actual`, `impact`, `evidence`, and `suggested_fix`. Text fields are bounded
to 8,192 characters; lists contain at most 20 items and each item is bounded
to 2,048 characters. A report must have at least one reproduction step and
one evidence item.

## Publishing rules

The operator searches `state:open` Issues with `dedupe_query` before creating
an Issue. A matching Issue is a duplicate candidate, not an automatic reason
to overwrite or close anything. The operator records the decision separately
and leaves the staged report pending when no publication is authorized.

`stage_report.py` permits at most five reports per agent per hour and twenty
per agent per UTC day by default. `publish_report.py` permits the same limits
per repository. Override only through the explicit `--max-per-hour` and
`--max-per-day` options in a controlled operator workflow.

The outbox is a transport boundary, not an audit archive. After publication,
retain only the sanitized envelope according to the operator's retention
policy. Never copy credentials or private deployment details into it.
