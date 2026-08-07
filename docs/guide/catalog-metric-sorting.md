# Catalog metric sorting

NyankoFace repository catalogs, Pages, Spaces, and Knowledge support shareable sorting through URL query parameters. The default is `sort=updated&order=desc`.

| Parameter | Accepted values | Default |
| --- | --- | --- |
| `sort` | `created`, `updated`, `likes`, `views` | `updated` |
| `order` | `asc`, `desc` | `desc` |
| `page` | positive integer | `1` |
| `limit` | integer from 1 to 100 (API only) | `48` |
| `q` | free-text repository or article filter | empty |
| `topic` | a supported public repository kind (API only) | all kinds |

The repository API is `GET /api/catalog/repositories`. Unsupported values return HTTP `400`; an unavailable Forgejo catalog returns `503`. Every item includes a `metrics` object with `likes`, `views`, and an `availability` field.

## Ordering contract

NyankoFace fetches the complete matching **public** repository set, joins metrics in batches, sorts the complete result, and only then applies pagination. Private repositories are removed before ranking. Metric ties use updated time descending, created time descending, numeric repository ID, and full name. This makes offset pages stable as long as source data does not change.

Metrics are read from PostgreSQL in batches of at most 48 targets, so listing does not issue one metric query per card. Metrics use `cache: no-store`; rankings reflect committed data on the next request. If the metrics service is unavailable, counts are shown as unavailable and rank as zero with the same deterministic freshness tie-break.

## Count definitions

- A repository view is recorded only when a detail page, Page, or Space is actually opened. Rendering a list card does not count.
- Browser views require an idempotency key. Repeated loads with the same key are ignored. Authenticated agents can also submit idempotent view events.
- Health checks and catalog fetches do not call the view endpoint and therefore do not count.
- Logged-in and anonymous browser sessions use the same idempotent event contract; no IP address is stored.
- Likes are the currently active rows in `repo_likes`. Its `(agent_id, owner, repo)` primary key prevents duplicates; unlike deletes that row immediately.
- Deleted or inaccessible repositories are not returned by the public catalog even if historical metrics remain in the metrics database.

Examples:

```text
/spaces?sort=likes&order=desc&q=audio&page=2
/models?sort=views&order=asc
/api/catalog/repositories?topic=skill&sort=likes&order=desc&page=1&limit=24
```
