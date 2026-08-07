import { getRepoMetricsBatch, type RepoAgentMetrics } from './agent-metrics';
import {
  searchAllReposByTopicAndQuery,
  type Repo,
  type RepoKind,
} from './forgejo';

export const CATALOG_SORTS = ['created', 'updated', 'likes', 'views'] as const;
export const SORT_ORDERS = ['asc', 'desc'] as const;
export const CATALOG_TOPICS = ['model', 'dataset', 'space', 'skill', 'mcp', 'prompt', 'doc', 'character', 'benchmark', 'automation'] as const;

export type CatalogSort = typeof CATALOG_SORTS[number];
export type SortOrder = typeof SORT_ORDERS[number];
export type RankedRepo = Repo & { metrics: RepoAgentMetrics };

export interface CatalogQuery {
  topic?: RepoKind;
  q?: string;
  sort: CatalogSort;
  order: SortOrder;
  page: number;
  limit: number;
}

export interface CatalogPage {
  ok: boolean;
  data: RankedRepo[];
  totalCount: number;
  page: number;
  limit: number;
  totalPages: number;
}

export function isCatalogSort(value: string | undefined): value is CatalogSort {
  return CATALOG_SORTS.includes(value as CatalogSort);
}

export function isSortOrder(value: string | undefined): value is SortOrder {
  return SORT_ORDERS.includes(value as SortOrder);
}

export function isDefaultCatalogOrdering(sort: CatalogSort, order: SortOrder): boolean {
  return sort === 'updated' && order === 'desc';
}

export function isCatalogTopic(value: string | undefined): value is RepoKind {
  return !value || CATALOG_TOPICS.includes(value as RepoKind);
}

export function parseCatalogQuery(input: {
  topic?: string;
  q?: string;
  sort?: string;
  order?: string;
  page?: string;
  limit?: string;
}): CatalogQuery {
  if (input.sort && !isCatalogSort(input.sort)) {
    throw new Error(`Unsupported sort: ${input.sort}`);
  }
  if (input.order && !isSortOrder(input.order)) {
    throw new Error(`Unsupported order: ${input.order}`);
  }
  if (input.topic && !isCatalogTopic(input.topic)) {
    throw new Error(`Unsupported topic: ${input.topic}`);
  }
  const page = input.page ? Number(input.page) : 1;
  const limit = input.limit ? Number(input.limit) : 48;
  if (!Number.isInteger(page) || page < 1) throw new Error('page must be a positive integer');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('limit must be between 1 and 100');
  return {
    ...(input.topic ? { topic: input.topic as RepoKind } : {}),
    ...(input.q?.trim() ? { q: input.q.trim() } : {}),
    sort: (input.sort as CatalogSort | undefined) || 'updated',
    order: (input.order as SortOrder | undefined) || 'desc',
    page,
    limit,
  };
}

function timestamp(value: string | undefined): number {
  const parsed = value ? Date.parse(value) : 0;
  return Number.isFinite(parsed) ? parsed : 0;
}

export function compareRankedRepos(
  left: RankedRepo,
  right: RankedRepo,
  sort: CatalogSort,
  order: SortOrder,
): number {
  const direction = order === 'asc' ? 1 : -1;
  const leftValue = sort === 'likes'
    ? left.metrics.likes
    : sort === 'views'
      ? left.metrics.views
      : timestamp(sort === 'created' ? left.created_at : left.updated_at);
  const rightValue = sort === 'likes'
    ? right.metrics.likes
    : sort === 'views'
      ? right.metrics.views
      : timestamp(sort === 'created' ? right.created_at : right.updated_at);
  const primary = (leftValue - rightValue) * direction;
  if (primary) return primary;

  // Metric ties intentionally remain fresh and deterministic regardless of
  // metric direction: updated desc, created desc, stable repository identity.
  const updated = timestamp(right.updated_at) - timestamp(left.updated_at);
  if (updated) return updated;
  const created = timestamp(right.created_at) - timestamp(left.created_at);
  if (created) return created;
  return (left.id || 0) - (right.id || 0) || left.full_name.localeCompare(right.full_name);
}

export function paginateRankedRepos(items: RankedRepo[], requestedPage: number, limit: number) {
  const totalPages = Math.max(1, Math.ceil(items.length / limit));
  const page = Math.min(requestedPage, totalPages);
  const start = (page - 1) * limit;
  return { data: items.slice(start, start + limit), page, totalPages };
}

export async function getCatalogPage(query: CatalogQuery): Promise<CatalogPage> {
  const result = await searchAllReposByTopicAndQuery(query.topic, query.q);
  if (!result.ok) {
    return { ok: false, data: [], totalCount: 0, page: query.page, limit: query.limit, totalPages: 1 };
  }
  const metrics = await getRepoMetricsBatch(result.data.map((repo) => ({
    owner: repo.owner?.login ?? repo.full_name.split('/')[0],
    repo: repo.name,
  })));
  const ranked = result.data.map((repo): RankedRepo => ({
    ...repo,
    metrics: metrics[repo.full_name] || {
      owner: repo.owner?.login ?? repo.full_name.split('/')[0],
      repo: repo.name,
      availability: 'unavailable',
      views: 0,
      likes: 0,
      recent_agents: [],
    },
  })).sort((left, right) => compareRankedRepos(left, right, query.sort, query.order));
  const paged = paginateRankedRepos(ranked, query.page, query.limit);
  return {
    ok: true,
    data: paged.data,
    totalCount: ranked.length,
    page: paged.page,
    limit: query.limit,
    totalPages: paged.totalPages,
  };
}
