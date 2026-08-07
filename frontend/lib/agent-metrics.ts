import fs from 'fs';

const FORGEJO_TOKEN_FILE = process.env.FORGEJO_TOKEN_FILE || '/shared/token';

function controlToken(): string | null {
  try {
    return fs.readFileSync(FORGEJO_TOKEN_FILE, 'utf8').trim() || null;
  } catch {
    return null;
  }
}

export interface RepoAgentMetrics {
  owner: string;
  repo: string;
  availability: 'available' | 'unavailable';
  views: number;
  agent_views?: number;
  browser_views?: number;
  likes: number;
  downloads?: number;
  downloads_by_source?: { raw: number; lfs: number; automation: number };
  recent_agents: Array<{
    slug: string;
    display_name: string;
    emoji: string;
    acted_at: string;
  }>;
}

export interface KnowledgeMetrics {
  owner: string;
  repo: string;
  slug: string;
  availability: 'available' | 'unavailable';
  views: number;
}

export type MetricDownloadSource = 'raw' | 'lfs' | 'automation';
export type MetricDownloadOutcome = 'success' | 'failed' | 'cancelled' | 'denied' | 'bot' | 'health_check';

const RUNNER_API = (process.env.RUNNER_API || 'http://spaces-runner:8000/api').replace(/\/$/, '');
const REPO_METRICS_BATCH_SIZE = 48;

function unavailableRepoMetrics(owner: string, repo: string): RepoAgentMetrics {
  return { owner, repo, availability: 'unavailable', views: 0, likes: 0, recent_agents: [] };
}

export async function getRepoMetrics(owner: string, repo: string): Promise<RepoAgentMetrics> {
  try {
    const response = await fetch(
      `${RUNNER_API}/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
      { cache: 'no-store' },
    );
    if (!response.ok) throw new Error(`metrics HTTP ${response.status}`);
    return { ...await response.json() as RepoAgentMetrics, availability: 'available' };
  } catch {
    return { owner, repo, availability: 'unavailable', views: 0, likes: 0, recent_agents: [] };
  }
}

export async function getRepoMetricsBatch(
  repos: Array<{ owner: string; repo: string }>,
  signal?: AbortSignal,
): Promise<Record<string, RepoAgentMetrics>> {
  if (repos.length === 0) return {};
  const uniqueRepos = [...new Map(repos.map((item) => [`${item.owner}/${item.repo}`, item])).values()];
  const chunks = Array.from(
    { length: Math.ceil(uniqueRepos.length / REPO_METRICS_BATCH_SIZE) },
    (_, index) => uniqueRepos.slice(index * REPO_METRICS_BATCH_SIZE, (index + 1) * REPO_METRICS_BATCH_SIZE),
  );
  const responses = await Promise.all(chunks.map(async (chunk) => {
    try {
      const response = await fetch(`${RUNNER_API}/metrics/repos/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repos: chunk }),
        cache: 'no-store',
        signal,
      });
      if (!response.ok) throw new Error(`metrics batch HTTP ${response.status}`);
      return await response.json() as Record<string, RepoAgentMetrics>;
    } catch {
      return {};
    }
  }));
  const merged = Object.assign({}, ...responses) as Record<string, RepoAgentMetrics>;
  return Object.fromEntries(uniqueRepos.map(({ owner, repo }) => {
    const key = `${owner}/${repo}`;
    const value = merged[key];
    return [key, value ? { ...value, availability: 'available' } : unavailableRepoMetrics(owner, repo)];
  }));
}

export async function getKnowledgeMetricsBatch(
  items: Array<{ owner: string; repo: string; slug: string }>,
): Promise<Record<string, KnowledgeMetrics>> {
  if (items.length === 0) return {};
  try {
    const response = await fetch(`${RUNNER_API}/metrics/knowledge/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`knowledge metrics HTTP ${response.status}`);
    const result = await response.json() as Record<string, KnowledgeMetrics>;
    return Object.fromEntries(items.map(({ owner, repo, slug }) => {
      const key = `${owner}/${repo}/${slug}`;
      const value = result[key];
      return [key, value
        ? { ...value, availability: 'available' }
        : { owner, repo, slug, availability: 'unavailable', views: 0 }];
    }));
  } catch {
    return Object.fromEntries(items.map(({ owner, repo, slug }) => [
      `${owner}/${repo}/${slug}`,
      { owner, repo, slug, availability: 'unavailable', views: 0 },
    ]));
  }
}

export async function recordDownloadMetric({
  owner,
  repo,
  source,
  artifactPath,
  idempotencyKey,
  outcome = 'success',
  actorKind = 'anonymous',
}: {
  owner: string;
  repo: string;
  source: MetricDownloadSource;
  artifactPath?: string | null;
  idempotencyKey: string;
  outcome?: MetricDownloadOutcome;
  actorKind?: 'anonymous' | 'authenticated' | 'system';
}): Promise<boolean> {
  try {
    const response = await fetch(
      `${RUNNER_API}/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/downloads`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-NyankoFace-Control-Token': controlToken() || '',
          'X-NyankoFace-Actor': actorKind,
        },
        body: JSON.stringify({
          source,
          artifact_path: artifactPath || null,
          idempotency_key: idempotencyKey,
          outcome,
        }),
        cache: 'no-store',
      },
    );
    return response.ok;
  } catch {
    return false;
  }
}
