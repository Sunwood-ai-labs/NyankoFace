import { getRepoMetricsBatch, type RepoAgentMetrics } from './agent-metrics';
import {
  getPagesInspection,
  searchRepos,
  type PagesInspection,
  type Repo,
  type SearchReposResult,
} from './forgejo';

const HOME_PAGES_PREVIEW_LIMIT = 3;
// Home discovery is deliberately a bounded hint, not a repository-wide
// catalog scan. Fetch one extra repository per page as a truncation sentinel,
// inspect one concurrent batch only, and abort all discovery after 1.5 seconds.
const HOME_PAGES_INSPECTION_LIMIT = 12;
const HOME_PAGES_RECENT_RESERVATION = 4;
const HOME_PAGES_SEARCH_LIMIT = HOME_PAGES_INSPECTION_LIMIT + 1;
const HOME_PAGES_MAX_SEARCH_PAGES = 4;
const HOME_PAGES_SEARCH_BUDGET_MS = 900;
const HOME_PAGES_LOAD_BUDGET_MS = 1_500;
const HOME_PAGES_CACHE_TTL_MS = 300_000;
const HOME_PAGES_FAILURE_CACHE_TTL_MS = 15_000;

let previewCache: { value: HomePagesPreview; expiresAt: number } | null = null;
let previewRequest: Promise<HomePagesPreview> | null = null;

export type HomePagesState = 'ready' | 'empty' | 'unavailable';

export interface PublishedPagePreview {
  repo: Repo;
  owner: string;
  publicUrl: string;
  source: 'gh-pages' | 'docs';
  metrics: RepoAgentMetrics;
}

export interface HomePagesPreview {
  state: HomePagesState;
  pages: PublishedPagePreview[];
}

export interface InspectedPageCandidate {
  repo: Repo;
  owner: string;
  inspection: PagesInspection;
}

function hasPagesTopic(repo: Repo): boolean {
  return (repo.topics || []).some((topic) => topic.toLowerCase() === 'pages');
}

export function mergeHomePagesRepositories(
  indexed: Repo[],
  recent: Repo[],
  limit = HOME_PAGES_INSPECTION_LIMIT,
): Repo[] {
  const indexedCandidates = [...indexed, ...recent.filter(hasPagesTopic)];
  const uniqueIndexed = [...new Map(indexedCandidates.map((repo) => [repo.full_name, repo])).values()];
  const indexedNames = new Set(uniqueIndexed.map((repo) => repo.full_name));
  const uniqueRecent = [...new Map(
    recent
      .filter((repo) => !hasPagesTopic(repo) && !indexedNames.has(repo.full_name))
      .map((repo) => [repo.full_name, repo]),
  ).values()];
  const recentReservation = Math.min(HOME_PAGES_RECENT_RESERVATION, uniqueRecent.length, limit);
  const indexedQuota = Math.max(0, limit - recentReservation);
  const prioritized = [
    ...uniqueIndexed.slice(0, indexedQuota),
    ...uniqueRecent.slice(0, recentReservation),
    ...uniqueIndexed.slice(indexedQuota),
    ...uniqueRecent.slice(recentReservation),
  ];
  return prioritized.slice(0, limit);
}

type RecentPageLoader = (page: number) => Promise<SearchReposResult>;

export async function fillRecentPagesReservation(
  indexed: Repo[],
  firstPage: SearchReposResult,
  loadPage: RecentPageLoader,
  pageSize = HOME_PAGES_SEARCH_LIMIT,
): Promise<SearchReposResult> {
  if (!firstPage.ok) return firstPage;

  const indexedNames = new Set(indexed.map((repo) => repo.full_name));
  const repositories = [...firstPage.data];
  const repositoryNames = new Set(repositories.map((repo) => repo.full_name));
  let totalCount = firstPage.upstream_total_count ?? firstPage.total_count;
  let inspectedCount = firstPage.upstream_inspected_count ?? firstPage.data.length;
  let nextPage = 2;

  const uniqueFallbackCount = () => repositories.reduce(
    (count, repo) => count + (
      indexedNames.has(repo.full_name) || hasPagesTopic(repo) ? 0 : 1
    ),
    0,
  );

  while (
    uniqueFallbackCount() < HOME_PAGES_RECENT_RESERVATION
    && (nextPage - 1) * pageSize < totalCount
    && nextPage <= HOME_PAGES_MAX_SEARCH_PAGES
  ) {
    const result = await loadPage(nextPage);
    if (!result.ok) {
      return {
        ok: false,
        data: repositories,
        total_count: repositories.length,
        upstream_total_count: totalCount,
        upstream_inspected_count: inspectedCount,
      };
    }
    totalCount = Math.max(totalCount, result.upstream_total_count ?? result.total_count);
    inspectedCount += result.upstream_inspected_count ?? result.data.length;
    for (const repo of result.data) {
      if (!repositoryNames.has(repo.full_name)) {
        repositories.push(repo);
        repositoryNames.add(repo.full_name);
      }
    }
    nextPage += 1;
  }

  return {
    ok: true,
    data: repositories,
    total_count: repositories.length,
    upstream_total_count: totalCount,
    upstream_inspected_count: inspectedCount,
  };
}

export function hasUninspectedSearchRows(
  result: Pick<SearchReposResult, 'total_count' | 'upstream_total_count' | 'upstream_inspected_count'>,
  publicRowCount: number,
): boolean {
  const upstreamTotal = result.upstream_total_count ?? result.total_count;
  const inspectedCount = result.upstream_inspected_count ?? publicRowCount;
  return upstreamTotal > inspectedCount;
}

function unavailableMetrics(owner: string, repo: string): RepoAgentMetrics {
  return { owner, repo, availability: 'unavailable', views: 0, likes: 0, recent_agents: [] };
}

export function selectPublishedPages(
  candidates: InspectedPageCandidate[],
  metrics: Record<string, RepoAgentMetrics>,
  limit = HOME_PAGES_PREVIEW_LIMIT,
): PublishedPagePreview[] {
  return candidates
    .filter(({ inspection }) => (
      inspection.status === 'published' &&
      Boolean(inspection.public_url) &&
      (inspection.source === 'gh-pages' || inspection.source === 'docs')
    ))
    .sort((left, right) => Date.parse(right.repo.updated_at) - Date.parse(left.repo.updated_at))
    .slice(0, limit)
    .map(({ repo, owner, inspection }) => ({
      repo,
      owner,
      publicUrl: inspection.public_url as string,
      source: inspection.source as 'gh-pages' | 'docs',
      metrics: metrics[repo.full_name] || unavailableMetrics(owner, repo.name),
    }));
}

export function resolveHomePagesState(
  repositorySearchOk: boolean,
  candidates: InspectedPageCandidate[],
  pages: PublishedPagePreview[],
  scanTruncated = false,
): HomePagesState {
  if (pages.length > 0) return 'ready';
  if (!repositorySearchOk) return 'unavailable';
  if (scanTruncated) return 'unavailable';
  if (candidates.some(({ inspection }) => inspection.status === 'error')) return 'unavailable';
  return 'empty';
}

/**
 * Build a small home-page preview without loading the complete catalog.
 * Publication remains governed by the gh-pages/docs file contract. The public
 * `pages` topic is the primary bounded discovery index. The recent-repo
 * fallback pages only until its topic-less reservation is full, with every
 * request sharing the same deadline, so supported untagged Pages stay visible.
 */
async function loadHomePagesPreview(): Promise<HomePagesPreview> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HOME_PAGES_LOAD_BUDGET_MS);
  // Catalog pagination gets only part of the full deadline. Keep the remaining
  // budget available for the concurrent publication checks and metrics fetch.
  const searchSignal = AbortSignal.any([
    controller.signal,
    AbortSignal.timeout(HOME_PAGES_SEARCH_BUDGET_MS),
  ]);
  try {
    const [indexedRepositories, firstRecentPage] = await Promise.all([
      searchRepos({
        topic: 'pages',
        sort: 'updated',
        limit: HOME_PAGES_SEARCH_LIMIT,
        page: 1,
        signal: searchSignal,
      }),
      searchRepos({
        sort: 'updated',
        limit: HOME_PAGES_SEARCH_LIMIT,
        page: 1,
        signal: searchSignal,
      }),
    ]);
    if (!indexedRepositories.ok && !firstRecentPage.ok) {
      return { state: 'unavailable', pages: [] };
    }
    const availableIndexed = indexedRepositories.ok ? indexedRepositories.data : [];
    const recentRepositories = await fillRecentPagesReservation(
      availableIndexed,
      firstRecentPage,
      (page) => searchRepos({
        sort: 'updated',
        limit: HOME_PAGES_SEARCH_LIMIT,
        page,
        signal: searchSignal,
      }),
    );
    // A later fallback page may time out after earlier pages succeeded. Keep
    // those accumulated candidates inspectable while `ok: false` continues to
    // mark the scan as truncated for empty/unavailable state resolution.
    const availableRecent = recentRepositories.data;
    const mergedRepositories = mergeHomePagesRepositories(
      availableIndexed,
      availableRecent,
      HOME_PAGES_INSPECTION_LIMIT,
    );
    const uniqueSearchCandidateCount = new Set(
      [...availableIndexed, ...availableRecent].map((repo) => repo.full_name),
    ).size;
    const repositoriesToInspect = mergedRepositories;
    const repositorySearchOk = indexedRepositories.ok && recentRepositories.ok;
    const scanTruncated = !repositorySearchOk
      || hasUninspectedSearchRows(indexedRepositories, availableIndexed.length)
      || hasUninspectedSearchRows(recentRepositories, availableRecent.length)
      || uniqueSearchCandidateCount > repositoriesToInspect.length;
    const candidates = await Promise.all(
      repositoriesToInspect.map(async (repo): Promise<InspectedPageCandidate> => {
        const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
        return {
          repo,
          owner,
          inspection: await getPagesInspection(owner, repo.name, controller.signal),
        };
      }),
    );
    const published = candidates.filter(({ inspection }) => (
      inspection.status === 'published' && Boolean(inspection.public_url)
    ));
    const metrics = await getRepoMetricsBatch(
      published.map(({ repo, owner }) => ({ owner, repo: repo.name })),
      controller.signal,
    );
    const pages = selectPublishedPages(candidates, metrics);
    return {
      state: resolveHomePagesState(repositorySearchOk, candidates, pages, scanTruncated),
      pages,
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function getHomePagesPreview(): Promise<HomePagesPreview> {
  if (previewCache && previewCache.expiresAt > Date.now()) return previewCache.value;
  if (!previewRequest) {
    previewRequest = loadHomePagesPreview()
      .then((value) => {
        const ttl = value.state === 'unavailable'
          ? HOME_PAGES_FAILURE_CACHE_TTL_MS
          : HOME_PAGES_CACHE_TTL_MS;
        previewCache = { value, expiresAt: Date.now() + ttl };
        return value;
      })
      .finally(() => {
        previewRequest = null;
      });
  }
  return previewRequest;
}
