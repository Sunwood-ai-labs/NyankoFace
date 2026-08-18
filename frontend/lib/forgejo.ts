import fs from 'fs';
import matter from 'gray-matter';
import { resolvePublicOrigin, sanitizePublicUrlRecord } from './public-origin';
import { safePublicUrl, sanitizePublicRepo } from './public-repo';

// ---------------------------------------------------------------------------
// Configuration (固定契約: PLAN.md)
// ---------------------------------------------------------------------------
const FORGEJO_API = process.env.FORGEJO_API || 'http://forgejo:3000/api/v1';
const FORGEJO_TOKEN_FILE = process.env.FORGEJO_TOKEN_FILE || '/shared/token';
const RUNNER_API = (process.env.RUNNER_API || 'http://spaces-runner:8000/api').replace(/\/$/, '');
const README_CACHE_TTL_MS = Math.max(
  60,
  Number.parseInt(process.env.README_CACHE_TTL_SECONDS || '300', 10) || 300,
) * 1000;
export const SKILL_MAX_BYTES = 256 * 1024;
const SKILL_ROOT_PATH = 'SKILL.md';
const SKILL_ROOT_MAX_BYTES = 256 * 1024;
export const PUBLIC_BASE_URL =
  process.env.PUBLIC_BASE_URL || 'http://localhost:8090';

let cachedToken: string | null | undefined;
const readmeCache = new Map<string, { value: string | null; expiresAt: number }>();
const skillRelationshipCache = new Map<string, { value: SkillRelationships; expiresAt: number }>();

function getToken(): string | null {
  if (cachedToken !== undefined) return cachedToken;
  try {
    const raw = fs.readFileSync(FORGEJO_TOKEN_FILE, 'utf-8');
    cachedToken = raw.trim() || null;
  } catch {
    // Token file missing — tolerate and fall back to unauthenticated requests.
    cachedToken = null;
  }
  return cachedToken;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface RepoOwner {
  login: string;
  avatar_url?: string;
}

export interface Repo {
  id: number;
  name: string;
  full_name: string;
  description: string | null;
  owner: RepoOwner;
  stars_count?: number;
  forks_count?: number;
  watchers_count?: number;
  open_issues_count?: number;
  created_at?: string;
  updated_at: string;
  topics?: string[];
  html_url?: string;
  default_branch?: string;
  space_emoji?: string;
  space_url?: string;
  skill_relationships?: SkillRelationships;
  private?: boolean;
}

const OPERATIONAL_DEFAULT_BRANCH = '__nyankofaceOperationalDefaultBranch';
type RepoWithOperationalDefaultBranch = Repo & {
  [key: string]: unknown;
};

function attachOperationalDefaultBranch(repo: Repo, branch: unknown): Repo {
  if (typeof branch !== 'string' || !branch.trim()) return repo;
  Object.defineProperty(repo, OPERATIONAL_DEFAULT_BRANCH, {
    configurable: true,
    enumerable: false,
    value: branch.trim(),
    writable: false,
  });
  return repo;
}

export function repoDefaultBranch(repo: Pick<Repo, 'default_branch'> | null | undefined): string {
  if (!repo) return 'main';
  const operational = (repo as RepoWithOperationalDefaultBranch)[OPERATIONAL_DEFAULT_BRANCH];
  if (typeof operational === 'string' && operational) return operational;
  const visible = repo.default_branch?.trim();
  return visible && visible !== '[internal URL omitted]' ? visible : 'main';
}

export function copyOperationalDefaultBranch<T extends Repo>(source: Pick<Repo, 'default_branch'>, target: T): T {
  return attachOperationalDefaultBranch(target, repoDefaultBranch(source)) as T;
}

export type SkillDependencyType = 'required' | 'recommended';

export interface SkillDependency {
  repo: string;
  type: SkillDependencyType;
  reason?: string;
  evidence?: string;
}

export interface SkillRelationships {
  schemaVersion: 1 | 2;
  dependencies: SkillDependency[];
}

export interface SearchReposResult {
  ok: boolean;
  data: Repo[];
  /** Public repositories returned after visibility filtering. */
  total_count: number;
  /** Raw Forgejo count used only to decide whether another upstream page exists. */
  upstream_total_count?: number;
  /** Number of raw repositories returned before private visibility filtering. */
  raw_page_size?: number;
  /** Number of raw Forgejo rows inspected before the public filter was applied. */
  upstream_inspected_count?: number;
}

export interface ContentEntry {
  name: string;
  path: string;
  type: 'file' | 'dir' | 'symlink' | 'submodule';
  size: number;
  sha: string;
  download_url?: string | null;
  content?: string | null;
  encoding?: string | null;
}

export interface GetContentsResult {
  ok: boolean;
  data: ContentEntry[] | ContentEntry | null;
}

type SkillRootStatus = 'valid' | 'invalid' | 'unavailable';

interface SkillEnrichmentResult {
  repos: Repo[];
  unavailable: boolean;
}

export interface PagesInspectionCheck {
  id: 'gh-pages_index' | 'docs_index';
  source: 'gh-pages' | 'docs';
  ref: string;
  path: string;
  ok: boolean;
  status: number;
}

export interface PagesInspection {
  owner: string;
  repo: string;
  public: boolean;
  default_branch: string;
  status: 'published' | 'missing' | 'private' | 'error';
  source: 'gh-pages' | 'docs' | null;
  source_ref: string | null;
  directory_prefix: string | null;
  index_path: string | null;
  public_url: string | null;
  checks: PagesInspectionCheck[];
  reasons: string[];
}

export type SortOption = 'updated' | 'stars';

export interface CommitInfo {
  sha: string;
  html_url?: string;
  commit?: {
    message?: string;
    author?: {
      name?: string;
      date?: string;
    };
    committer?: {
      name?: string;
      date?: string;
    };
  };
  author?: RepoOwner | null;
  committer?: RepoOwner | null;
}

export interface RepoTag {
  name: string;
  message?: string;
  commit?: {
    sha?: string;
    created?: string;
  };
}

// ---------------------------------------------------------------------------
// Low-level fetch helper — never throws; callers get {ok:false} on failure so
// pages can render an empty-state instead of crashing SSR / the build.
// ---------------------------------------------------------------------------
async function apiFetch(
  path: string,
  signal?: AbortSignal,
): Promise<{ ok: boolean; status: number; json: any; headers: Headers | null }> {
  const token = getToken();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers['Authorization'] = `token ${token}`;

  const url = `${FORGEJO_API}${path}`;
  try {
    const res = await fetch(url, {
      headers,
      cache: 'no-store',
      signal,
    });
    let json: any = null;
    try {
      json = await res.json();
    } catch {
      json = null;
    }
    return { ok: res.ok, status: res.status, json, headers: res.headers };
  } catch (err) {
    // Network error (Forgejo down, DNS failure, etc.)
    return { ok: false, status: 0, json: null, headers: null };
  }
}

// ---------------------------------------------------------------------------
// Repo search — topic-classified listing (models / datasets / spaces)
// ---------------------------------------------------------------------------
export type RepoKind = 'model' | 'dataset' | 'space' | 'skill' | 'mcp' | 'prompt' | 'doc' | 'character' | 'benchmark' | 'automation';
export type RepoSearchTopic = RepoKind | 'pages';

export interface SearchReposParams {
  topic?: RepoSearchTopic;
  q?: string;
  sort?: SortOption;
  limit?: number;
  page?: number;
  signal?: AbortSignal;
}

async function fetchRepoSearchPage(params: SearchReposParams): Promise<SearchReposResult> {
  const { topic, q, sort = 'updated', limit = 20, page = 1, signal } = params;

  const qs = new URLSearchParams();
  // Forgejo topic search contract: GET /repos/search?q=<topic>&topic=true
  if (topic) {
    qs.set('q', topic);
    qs.set('topic', 'true');
  } else if (q) {
    qs.set('q', q);
  }
  qs.set('limit', String(limit));
  qs.set('page', String(page));

  if (sort === 'stars') {
    qs.set('sort', 'stars');
    qs.set('order', 'desc');
  } else {
    qs.set('sort', 'updated');
    qs.set('order', 'desc');
  }

  // Additional free-text query on top of a topic listing (e.g. /models?q=bert)
  if (topic && q) {
    qs.set('q', q);
    qs.append('topic', 'false');
  }

  const res = await apiFetch(`/repos/search?${qs.toString()}`, signal);
  if (!res.ok || !res.json) {
    return { ok: false, data: [], total_count: 0, upstream_total_count: 0 };
  }
  // This server-side client uses the seed admin token to read repository
  // metadata. Never let that privileged token turn private Forgejo assets into
  // public NyankoFace catalog entries.
  const upstreamData = Array.isArray(res.json.data) ? res.json.data as Repo[] : [];
  const data = upstreamData
    .filter((repo) => !repo.private)
    .map(sanitizePublicRepo);
  const headerTotal = Number.parseInt(res.headers?.get('x-total-count') || '', 10);
  return {
    ok: true,
    data,
    total_count: data.length,
    upstream_total_count: Number.isFinite(headerTotal) ? headerTotal : upstreamData.length,
    raw_page_size: upstreamData.length,
    upstream_inspected_count: upstreamData.length,
  };
}

function rawSearchPageBudget(rawTotal: number, rawPageSize: number): number {
  if (rawTotal <= 0) return 1;
  if (rawPageSize <= 0) return 0;
  return Math.max(1, Math.ceil(rawTotal / rawPageSize));
}

async function searchSkillRepos(params: SearchReposParams): Promise<SearchReposResult> {
  const limit = Math.max(1, params.limit || 20);
  const requestedPage = Math.max(1, params.page || 1);
  const firstAdmittedIndex = (requestedPage - 1) * limit;
  const targetAdmittedCount = firstAdmittedIndex + limit;
  const admitted: Repo[] = [];
  let rawTotal = 0;
  let rawFetched = 0;
  let rawExhausted = false;
  let maxRawPages = 1;

  for (let rawPage = 1; rawPage <= maxRawPages; rawPage += 1) {
    const result = await fetchRepoSearchPage({ ...params, limit, page: rawPage });
    if (!result.ok) return result;
    rawTotal = result.upstream_total_count ?? result.total_count;
    const rawPageSize = result.upstream_inspected_count ?? result.raw_page_size ?? result.data.length;
    if (rawPage === 1) maxRawPages = rawSearchPageBudget(rawTotal, rawPageSize);
    rawFetched += rawPageSize;

    // A paged listing only needs enough admitted Skills for the requested
    // page. The complete catalog path below remains responsible for exact
    // totals and full relationship enrichment.
    const skillResult = await enrichSkillMetadata(result.data, targetAdmittedCount - admitted.length);
    if (skillResult.unavailable) return { ok: false, data: [], total_count: 0 };
    admitted.push(...skillResult.repos);

    if (admitted.length >= targetAdmittedCount) {
      return {
        ok: true,
        data: admitted.slice(firstAdmittedIndex, targetAdmittedCount),
        total_count: admitted.length,
      };
    }
    if (rawFetched >= rawTotal) {
      rawExhausted = true;
      break;
    }
    if (rawPageSize === 0) break;
  }

  if (!rawExhausted) return { ok: false, data: [], total_count: 0 };

  return {
    ok: true,
    data: admitted.slice(firstAdmittedIndex, firstAdmittedIndex + limit),
    total_count: admitted.length,
  };
}

export async function searchRepos(params: SearchReposParams): Promise<SearchReposResult> {
  const { topic } = params;
  if (topic === 'skill') return searchSkillRepos(params);

  const result = await fetchRepoSearchPage(params);
  if (!result.ok) return result;
  let enrichedData = result.data;
  if (topic === 'space') {
    enrichedData = await enrichSpaceMetadata(result.data);
  }
  return {
    ...result,
    data: enrichedData.map(sanitizePublicRepo),
  };
}

/**
 * Metric-backed rankings (likes/views) must be calculated before pagination.
 * Forgejo can order repository metadata, but NyankoFace likes live in the local
 * metrics store, so fetch the complete public topic set first and let callers
 * rank it once. This intentionally stays separate from the normal paged
 * metadata query used by "recently updated" listings.
 */
export async function searchAllReposByTopicAndQuery(
  topic: RepoKind | undefined,
  q?: string,
): Promise<SearchReposResult> {
  if (topic === 'skill') return searchAllSkillReposByTopicAndQuery(q);

  const pageSize = 100;
  let page = 1;
  let expectedTotal = Number.POSITIVE_INFINITY;
  let rawFetched = 0;
  let rawExhausted = false;
  let maxRawPages = 1;
  const repos: Repo[] = [];

  for (page = 1; page <= maxRawPages && rawFetched < expectedTotal; page += 1) {
    const result = await searchRepos({ topic, q: topic ? undefined : q, sort: 'updated', limit: pageSize, page });
    if (!result.ok) return { ok: false, data: [], total_count: 0 };
    repos.push(...result.data);
    expectedTotal = result.upstream_total_count ?? result.total_count;
    const rawPageSize = result.upstream_inspected_count ?? result.raw_page_size ?? result.data.length;
    if (page === 1) maxRawPages = rawSearchPageBudget(expectedTotal, rawPageSize);
    rawFetched += rawPageSize;
    // `data` excludes private repositories, while Forgejo's total still
    // describes the raw result set. Do not stop just because a page became
    // shorter after that safety filter; otherwise a later public page could
    // be omitted from the global metric ranking.
    if (rawFetched >= expectedTotal) {
      rawExhausted = true;
      break;
    }
    if (rawPageSize === 0) break;
  }

  if (!rawExhausted) return { ok: false, data: [], total_count: 0 };

  const needle = q?.toLowerCase();
  const filtered = needle
    ? repos.filter((repo) =>
        repo.name.toLowerCase().includes(needle) ||
        (repo.description || '').toLowerCase().includes(needle) ||
        repo.full_name.toLowerCase().includes(needle) ||
        (repo.topics || []).some((repoTopic) => repoTopic.toLowerCase().includes(needle)),
      )
    : repos;
  return { ok: true, data: filtered, total_count: filtered.length };
}

async function searchAllSkillReposByTopicAndQuery(q?: string): Promise<SearchReposResult> {
  const pageSize = 100;
  const repos: Repo[] = [];
  let rawTotal = Number.POSITIVE_INFINITY;
  let rawFetched = 0;
  let rawExhausted = false;
  let maxRawPages = 1;

  for (let page = 1; page <= maxRawPages; page += 1) {
    const result = await fetchRepoSearchPage({ topic: 'skill', sort: 'updated', limit: pageSize, page });
    if (!result.ok) return result;
    rawTotal = result.upstream_total_count ?? result.total_count;
    const rawPageSize = result.upstream_inspected_count ?? result.raw_page_size ?? result.data.length;
    if (page === 1) maxRawPages = rawSearchPageBudget(rawTotal, rawPageSize);
    rawFetched += rawPageSize;
    const skillResult = await enrichSkillMetadata(result.data);
    if (skillResult.unavailable) return { ok: false, data: [], total_count: 0 };
    repos.push(...skillResult.repos);
    if (rawFetched >= rawTotal) {
      rawExhausted = true;
      break;
    }
    if (rawPageSize === 0) break;
  }

  if (!rawExhausted) return { ok: false, data: [], total_count: 0 };

  const needle = q?.toLowerCase();
  const filtered = needle
    ? repos.filter((repo) =>
        repo.name.toLowerCase().includes(needle) ||
        (repo.description || '').toLowerCase().includes(needle) ||
        repo.full_name.toLowerCase().includes(needle) ||
        (repo.topics || []).some((repoTopic) => repoTopic.toLowerCase().includes(needle)),
      )
    : repos;
  return { ok: true, data: filtered, total_count: filtered.length };
}

// When both a topic (model/dataset/space) and a free-text query are needed,
// Forgejo's single-endpoint search doesn't combine "topic-only" filtering
// with a fuzzy text query cleanly. To keep behaviour predictable we search
// by topic and then filter client-side (server-side/SSR) by the query text
// against name/description. This keeps the "固定契約" endpoint shape intact
// while still giving usable search-within-category behaviour.
export async function searchReposByTopicAndQuery(
  topic: RepoKind,
  q: string | undefined,
  sort: SortOption,
  limit = 50,
  page = 1,
): Promise<SearchReposResult> {
  const res = await searchRepos({ topic, sort, limit, page });
  if (!q) return res;
  const needle = q.toLowerCase();
  const filtered = res.data.filter((r) => {
    return (
      r.name.toLowerCase().includes(needle) ||
      (r.description || '').toLowerCase().includes(needle) ||
      r.full_name.toLowerCase().includes(needle) ||
      (r.topics || []).some((repoTopic) => repoTopic.toLowerCase().includes(needle))
    );
  });
  return {
    ok: res.ok,
    data: filtered,
    total_count: filtered.length,
    upstream_total_count: res.upstream_total_count,
    raw_page_size: res.raw_page_size,
    upstream_inspected_count: res.upstream_inspected_count,
  };
}

// ---------------------------------------------------------------------------
// Single repo
// ---------------------------------------------------------------------------
export async function getRepo(owner: string, repo: string): Promise<Repo | null> {
  const res = await apiFetch(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`);
  if (!res.ok || !res.json || res.json.private) return null;
  const repoInfo = sanitizePublicRepo(res.json as Repo);
  const kind = repoKind(repoInfo.topics);
  if (kind === 'space') return sanitizePublicRepo((await enrichSpaceMetadata([repoInfo]))[0]);
  if (kind === 'skill') {
    const skillResult = await enrichSkillMetadata([repoInfo]);
    const enriched = skillResult.repos[0];
    return skillResult.unavailable || !enriched ? null : sanitizePublicRepo(enriched);
  }
  return repoInfo;
}

async function publicApiFetch(
  path: string,
): Promise<{ ok: boolean; status: number; json: any }> {
  try {
    const response = await fetch(`${FORGEJO_API}${path}`, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    let json: any = null;
    try {
      json = await response.json();
    } catch {
      json = null;
    }
    return { ok: response.ok, status: response.status, json };
  } catch {
    return { ok: false, status: 0, json: null };
  }
}

export interface PublicRepoRevision {
  repo: Repo;
  requestedRef: string;
  sha: string;
}

/**
 * Resolve a public repository ref without the privileged seed token.
 * Automation preflight and download both pin every file read to this SHA.
 */
export async function resolvePublicRepoRevision(
  owner: string,
  repo: string,
  requestedRef?: string,
): Promise<PublicRepoRevision | null> {
  const encodedOwner = encodeURIComponent(owner);
  const encodedRepo = encodeURIComponent(repo);
  const repoResponse = await publicApiFetch(`/repos/${encodedOwner}/${encodedRepo}`);
  if (!repoResponse.ok || !repoResponse.json || repoResponse.json.private) return null;
  const rawRepoInfo = repoResponse.json as Repo;
  const repoInfo = sanitizePublicRepo(rawRepoInfo);
  const rawDefaultBranch = typeof rawRepoInfo.default_branch === 'string'
    ? rawRepoInfo.default_branch.trim()
    : '';
  const ref = requestedRef?.trim() || rawDefaultBranch || 'main';
  const commitResponse = await publicApiFetch(
    `/repos/${encodedOwner}/${encodedRepo}/git/commits/${encodeURIComponent(ref)}`,
  );
  const sha = typeof commitResponse.json?.sha === 'string' ? commitResponse.json.sha : '';
  if (!commitResponse.ok || !/^[a-f0-9]{40,64}$/i.test(sha)) return null;
  return { repo: repoInfo, requestedRef: ref, sha };
}

export async function getPublicTextFileAtRevision(
  owner: string,
  repo: string,
  path: string,
  sha: string,
  maxBytes = 256 * 1024,
): Promise<string | null> {
  const cleanPath = path.replace(/^\/+/, '');
  if (
    !cleanPath ||
    cleanPath.includes('..') ||
    cleanPath.includes('\\') ||
    !/^[a-f0-9]{40,64}$/i.test(sha)
  ) {
    return null;
  }
  const response = await publicApiFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${encodeURIComponent(cleanPath)}?ref=${encodeURIComponent(sha)}`,
  );
  const entry = response.json as ContentEntry | null;
  if (
    !response.ok ||
    !entry ||
    entry.type !== 'file' ||
    typeof entry.content !== 'string' ||
    entry.size > maxBytes
  ) {
    return null;
  }
  try {
    const content = Buffer.from(
      entry.content,
      (entry.encoding as BufferEncoding) || 'base64',
    );
    if (content.byteLength > maxBytes) return null;
    return content.toString('utf-8');
  } catch {
    return null;
  }
}

export async function getPagesInspection(
  owner: string,
  repo: string,
  signal?: AbortSignal,
): Promise<PagesInspection> {
  try {
    const response = await fetch(
      `${RUNNER_API}/pages/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/status`,
      { cache: 'no-store', headers: { Accept: 'application/json' }, signal },
    );
    if (response.ok) return sanitizePublicUrlRecord(await response.json()) as PagesInspection;
    return {
      owner,
      repo,
      public: true,
      default_branch: 'main',
      status: 'error',
      source: null,
      source_ref: null,
      directory_prefix: null,
      index_path: null,
      public_url: null,
      checks: [],
      reasons: [`Pages inspection failed with HTTP ${response.status}.`],
    };
  } catch {
    return {
      owner,
      repo,
      public: true,
      default_branch: 'main',
      status: 'error',
      source: null,
      source_ref: null,
      directory_prefix: null,
      index_path: null,
      public_url: null,
      checks: [],
      reasons: ['Pages inspection is temporarily unavailable.'],
    };
  }
}

// ---------------------------------------------------------------------------
// Directory / file listing
// ---------------------------------------------------------------------------
export async function getContents(
  owner: string,
  repo: string,
  path: string = '',
  ref?: string,
): Promise<GetContentsResult> {
  const cleanPath = path.replace(/^\/+/, '');
  const query = ref ? `?ref=${encodeURIComponent(ref)}` : '';
  const res = await apiFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${cleanPath}${query}`
  );
  if (!res.ok || res.json === null) {
    return { ok: false, data: null };
  }
  return { ok: true, data: res.json };
}

export async function getRepoTags(owner: string, repo: string): Promise<RepoTag[]> {
  const res = await apiFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/tags?limit=100`,
  );
  if (!res.ok || !Array.isArray(res.json)) return [];
  return (res.json as RepoTag[]).sort((left, right) =>
    right.name.localeCompare(left.name, undefined, { numeric: true, sensitivity: 'base' }),
  );
}

export async function getCommits(
  owner: string,
  repo: string,
  path = '',
  limit = 10
): Promise<CommitInfo[]> {
  const qs = new URLSearchParams();
  qs.set('limit', String(limit));
  if (path) qs.set('path', path.replace(/^\/+/, ''));
  const res = await apiFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/commits?${qs.toString()}`
  );
  if (!res.ok || !Array.isArray(res.json)) return [];
  return res.json as CommitInfo[];
}

// ---------------------------------------------------------------------------
// Raw file content (text) — via /raw/ endpoint
// ---------------------------------------------------------------------------
export async function getRawFile(
  owner: string,
  repo: string,
  path: string,
  ref?: string,
): Promise<string | null> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `token ${token}`;
  const cleanPath = path.replace(/^\/+/, '');
  const url = `${FORGEJO_API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(
    repo
  )}/raw/${cleanPath}${ref ? `?ref=${encodeURIComponent(ref)}` : ''}`;
  try {
    const res = await fetch(url, { headers, cache: 'no-store' });
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}

export async function getTextFile(
  owner: string,
  repo: string,
  path: string,
  ref?: string,
): Promise<string | null> {
  const res = await getContents(owner, repo, path, ref);
  if (!res.ok || !res.data || Array.isArray(res.data) || !res.data.content) return null;
  try {
    return Buffer.from(
      res.data.content,
      (res.data.encoding as BufferEncoding) || 'base64',
    ).toString('utf-8');
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// README (base64 decode via contents API)
// ---------------------------------------------------------------------------
export async function getReadme(owner: string, repo: string, ref?: string): Promise<string | null> {
  const cacheKey = `${owner}/${repo}@${ref || 'default'}`;
  const cached = readmeCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const value = await getTextFile(owner, repo, 'README.md', ref);
  readmeCache.set(cacheKey, { value, expiresAt: Date.now() + README_CACHE_TTL_MS });
  return value;
}

function normalizeSkillDependency(value: unknown): SkillDependency | null {
  if (typeof value === 'string') {
    const repo = value.trim();
    return repo ? { repo, type: 'recommended' } : null;
  }
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Record<string, unknown>;
  const repo = typeof candidate.repo === 'string' ? candidate.repo.trim() : '';
  if (!repo) return null;
  const type: SkillDependencyType = candidate.type === 'required' ? 'required' : 'recommended';
  const reason = typeof candidate.reason === 'string' ? candidate.reason.trim() : '';
  const evidence = typeof candidate.evidence === 'string' ? candidate.evidence.trim() : '';
  return { repo, type, ...(reason ? { reason } : {}), ...(evidence ? { evidence } : {}) };
}

export async function getSkillRelationships(owner: string, repo: string): Promise<SkillRelationships> {
  const cacheKey = `${owner}/${repo}`;
  const cached = skillRelationshipCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.value;

  const raw = await getTextFile(owner, repo, 'skill.json');
  let value: SkillRelationships = { schemaVersion: 2, dependencies: [] };
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const dependencies = Array.isArray(parsed.dependencies)
        ? parsed.dependencies.map(normalizeSkillDependency).filter((item): item is SkillDependency => item !== null)
        : [];
      value = { schemaVersion: parsed.schemaVersion === 1 ? 1 : 2, dependencies };
    } catch {
      value = { schemaVersion: 2, dependencies: [] };
    }
  }
  skillRelationshipCache.set(cacheKey, { value, expiresAt: Date.now() + README_CACHE_TTL_MS });
  return value;
}

function normalizeEmoji(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    const first = new Intl.Segmenter('en', { granularity: 'grapheme' })
      .segment(trimmed)[Symbol.iterator]().next().value?.segment as string | undefined;
    if (!first || !/[\p{Extended_Pictographic}\p{Regional_Indicator}]/u.test(first)) return undefined;
    return first;
  } catch {
    return Array.from(trimmed)[0];
  }
}

function normalizeExternalSpaceUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 2048) return undefined;
  const safe = safePublicUrl(trimmed);
  return safe && !safe.startsWith('/') ? safe : undefined;
}

function inferredSpaceEmoji(repo: Repo): string {
  const text = [repo.name, repo.description || '', ...(repo.topics || [])].join(' ').toLowerCase();
  if (/wildlife|bird|animal/.test(text)) return '🦅';
  if (/webgpu|kernel|gpu/.test(text)) return '⚡';
  if (/train|trainer|lora|fine-tun/.test(text)) return '🧪';
  if (/table|chart|csv|data-viz|visualization/.test(text)) return '📊';
  if (/video|movie|animation/.test(text)) return '🎬';
  if (/audio-clean|noise|sound/.test(text)) return '🎧';
  if (/voice|speech|microphone|realtime/.test(text)) return '🎙️';
  if (/chat|question|answer/.test(text)) return '💬';
  if (/document|pdf|ocr/.test(text)) return '📄';
  if (/image|vision|photo|visual/.test(text)) return '🖼️';
  if (/code|agent/.test(text)) return '🤖';
  return '🚀';
}

async function enrichSpaceMetadata(repos: Repo[]): Promise<Repo[]> {
  return Promise.all(repos.map(async (repo) => {
    const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
    const branch = repoDefaultBranch(repo);
    const readme = await getReadme(owner, repo.name);
    let configuredEmoji: string | undefined;
    let configuredExternalUrl: string | undefined;
    if (readme) {
      try {
        const frontmatter = matter(readme).data;
        configuredEmoji = normalizeEmoji(frontmatter?.emoji);
        configuredExternalUrl = normalizeExternalSpaceUrl(frontmatter?.external_url);
      } catch {
        configuredEmoji = undefined;
        configuredExternalUrl = undefined;
      }
    }
    return attachOperationalDefaultBranch({
      ...repo,
      space_emoji: configuredEmoji || inferredSpaceEmoji(repo),
      ...(configuredExternalUrl ? { space_url: configuredExternalUrl } : {}),
    }, branch);
  }));
}

function isSkillRootUnavailable(status: number): boolean {
  return status === 0 || status === 408 || status === 425 || status === 429 || status >= 500;
}

function decodeSkillRootContent(entry: unknown): string | null {
  if (
    !entry
    || typeof entry !== 'object'
    || Array.isArray(entry)
  ) {
    return null;
  }
  const candidate = entry as Partial<ContentEntry>;
  const size = candidate.size;
  if (
    candidate.name !== SKILL_ROOT_PATH
    || candidate.path !== SKILL_ROOT_PATH
    || candidate.type !== 'file'
    || typeof size !== 'number'
    || !Number.isSafeInteger(size)
    || size <= 0
    || size > SKILL_ROOT_MAX_BYTES
    || typeof candidate.content !== 'string'
    || !candidate.content
    || typeof candidate.encoding !== 'string'
    || candidate.encoding.toLowerCase() !== 'base64'
  ) {
    return null;
  }

  const encoded = candidate.content.replace(/\s+/g, '');
  if (
    !encoded
    || encoded.length % 4 !== 0
    || encoded.length > Math.ceil(SKILL_MAX_BYTES / 3) * 4
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)
  ) {
    return null;
  }

  const bytes = Buffer.from(encoded, 'base64');
  if (
    bytes.byteLength !== size
    || bytes.byteLength > SKILL_ROOT_MAX_BYTES
    || bytes.toString('base64') !== encoded
  ) {
    return null;
  }

  try {
    const content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    return content.trim() ? content : null;
  } catch {
    return null;
  }
}

function hasRequiredSkillFrontmatter(content: string): boolean {
  try {
    const data = matter(content).data as Record<string, unknown>;
    return (
      typeof data.name === 'string'
      && Boolean(data.name.trim())
      && typeof data.description === 'string'
      && Boolean(data.description.trim())
    );
  } catch {
    return false;
  }
}

async function getSkillRootStatus(owner: string, repo: string): Promise<SkillRootStatus> {
  const res = await apiFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${SKILL_ROOT_PATH}`,
  );
  if (!res.ok) return isSkillRootUnavailable(res.status) ? 'unavailable' : 'invalid';
  const content = decodeSkillRootContent(res.json as ContentEntry);
  return content && hasRequiredSkillFrontmatter(content) ? 'valid' : 'invalid';
}

async function enrichSkillMetadata(repos: Repo[], maxAdmitted = Number.POSITIVE_INFINITY): Promise<SkillEnrichmentResult> {
  const enrichOne = async (repo: Repo): Promise<{ repo: Repo | null; unavailable: boolean }> => {
    const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
    const rootStatus = await getSkillRootStatus(owner, repo.name);
    if (rootStatus === 'unavailable') return { repo: null, unavailable: true };
    if (rootStatus !== 'valid') return { repo: null, unavailable: false };
    const enriched = attachOperationalDefaultBranch({
      ...repo,
      skill_relationships: await getSkillRelationships(owner, repo.name),
    }, repoDefaultBranch(repo));
    return {
      repo: sanitizePublicRepo(enriched),
      unavailable: false,
    };
  };
  if (Number.isFinite(maxAdmitted)) {
    const admitted: Repo[] = [];
    for (const repo of repos) {
      if (admitted.length >= maxAdmitted) break;
      const result = await enrichOne(repo);
      if (result.unavailable) return { repos: [], unavailable: true };
      if (result.repo) admitted.push(result.repo);
    }
    return { repos: admitted, unavailable: false };
  }

  const results = await Promise.all(repos.map(enrichOne));
  return {
    repos: results.flatMap((result) => result.repo ? [result.repo] : []),
    unavailable: results.some((result) => result.unavailable),
  };
}

// ---------------------------------------------------------------------------
// LFS pointer detection
// ---------------------------------------------------------------------------
const LFS_POINTER_PREFIX = 'version https://git-lfs.github.com/spec/v1';

export function isLfsPointer(content: string): boolean {
  return content.trimStart().startsWith(LFS_POINTER_PREFIX);
}

export function lfsMediaUrl(owner: string, repo: string, path: string, branch = 'main'): string {
  return `/git/${owner}/${repo}/media/branch/${branch}/${path}`;
}

// ---------------------------------------------------------------------------
// Misc helpers
// ---------------------------------------------------------------------------
export function cloneUrl(owner: string, repo: string, requestOrigin?: string): string {
  const publicOrigin = resolvePublicOrigin(PUBLIC_BASE_URL, requestOrigin);
  if (publicOrigin) return `${publicOrigin}/git/${owner}/${repo}.git`;
  try {
    const localOrigin = new URL(requestOrigin || '');
    if ((localOrigin.protocol === 'http:' || localOrigin.protocol === 'https:') && !localOrigin.username && !localOrigin.password) {
      return `${localOrigin.origin}/git/${owner}/${repo}.git`;
    }
  } catch {
    // Fall back to the portal-relative path when no usable request origin exists.
  }
  return `/git/${owner}/${repo}.git`;
}

export function forgejoRepoUrl(owner: string, repo: string): string {
  return `/git/${owner}/${repo}`;
}

export function forgejoTreeUrl(owner: string, repo: string, path = '', branch = 'main', refKind: 'branch' | 'tag' = 'branch'): string {
  const cleanPath = path.replace(/^\/+/, '');
  return `${forgejoRepoUrl(owner, repo)}/src/${refKind}/${branch}${cleanPath ? `/${cleanPath}` : ''}`;
}

export function forgejoRawUrl(owner: string, repo: string, path: string, branch = 'main', refKind: 'branch' | 'tag' = 'branch'): string {
  return `${forgejoRepoUrl(owner, repo)}/raw/${refKind}/${branch}/${path.replace(/^\/+/, '')}`;
}

export type DownloadSource = 'raw' | 'lfs' | 'automation';

export function nyankofaceDownloadUrl(
  owner: string,
  repo: string,
  path: string,
  branch = 'main',
  source: DownloadSource = 'raw',
  refKind: 'branch' | 'tag' = 'branch',
): string {
  const params = new URLSearchParams({
    path: path.replace(/^\/+/, ''),
    ref: branch,
    kind: source,
    refKind,
  });
  return `/api/download/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}?${params.toString()}`;
}

export function forgejoCommitsUrl(owner: string, repo: string, path = '', branch = 'main'): string {
  const cleanPath = path.replace(/^\/+/, '');
  return `${forgejoRepoUrl(owner, repo)}/commits/branch/${branch}${cleanPath ? `/${cleanPath}` : ''}`;
}

const TYPE_TOPICS = new Set<string>(['model', 'dataset', 'space', 'skill', 'mcp', 'prompt', 'doc', 'character', 'benchmark', 'automation']);

const VERSION_TOPIC = /^version-(v\d+(?:\.\d+)*)$/i;

export function nonTypeTopics(topics: string[] | undefined): string[] {
  if (!topics) return [];
  return topics.filter((t) => !TYPE_TOPICS.has(t) && !VERSION_TOPIC.test(t));
}

export function repoPromptVersion(topics: string[] | undefined): string | null {
  if (!topics) return null;
  const version = topics.find((topic) => VERSION_TOPIC.test(topic));
  return version ? version.replace(/^version-/i, '') : null;
}

export function repoKind(topics: string[] | undefined): RepoKind | null {
  if (!topics) return null;
  if (topics.includes('space')) return 'space';
  if (topics.includes('dataset')) return 'dataset';
  if (topics.includes('model')) return 'model';
  if (topics.includes('character')) return 'character';
  if (topics.includes('skill')) return 'skill';
  if (topics.includes('mcp')) return 'mcp';
  if (topics.includes('prompt')) return 'prompt';
  if (topics.includes('doc')) return 'doc';
  if (topics.includes('benchmark')) return 'benchmark';
  if (topics.includes('automation')) return 'automation';
  return null;
}
