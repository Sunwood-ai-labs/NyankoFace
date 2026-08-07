export type BrowserViewMetrics = {
  views?: number;
  likes?: number;
};

type BrowserViewResponse = {
  metrics?: BrowserViewMetrics;
};

// The Space header and the detail panel mount independently. Keep one request
// per real page load so the panel can wait for the same view write as the header.
const viewRequests = new Map<string, Promise<BrowserViewMetrics | null>>();

export function browserViewIdempotencyKey(owner: string, repo: string): string {
  return `browser:${owner}/${repo}:${performance.timeOrigin}`;
}

export function ensureBrowserView(owner: string, repo: string): Promise<BrowserViewMetrics | null> {
  const idempotencyKey = browserViewIdempotencyKey(owner, repo);
  const existing = viewRequests.get(idempotencyKey);
  if (existing) return existing;

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort('timeout'), 8_000);
  const request = fetch(`/runner-api/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/views`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    signal: controller.signal,
  })
    .then((response) => response.ok ? response.json() as Promise<BrowserViewResponse> : null)
    .then((result) => result?.metrics ?? null)
    .catch(() => null)
    .finally(() => window.clearTimeout(timeout));

  viewRequests.set(idempotencyKey, request);
  return request;
}
