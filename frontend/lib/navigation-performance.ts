export const NAVIGATION_ROUTE_CLASSES = [
  'home',
  'catalog',
  'knowledge-list',
  'knowledge-detail',
  'repository-detail',
  'pages-deploy',
  'create',
  'search',
  'forgejo',
  'other',
] as const;

export type NavigationRouteClass = (typeof NAVIGATION_ROUTE_CLASSES)[number];
export type NavigationOutcome = 'success' | 'cancelled' | 'timeout' | 'error';
export type NavigationViewport = 'desktop' | 'mobile';
export type NavigationCacheState = 'cold' | 'warm';

export interface NavigationSample {
  route: NavigationRouteClass;
  durationMs: number;
  feedbackMs: number;
  outcome: NavigationOutcome;
  viewport: NavigationViewport;
  cache: NavigationCacheState;
}

export interface NavigationSummary {
  route: NavigationRouteClass;
  count: number;
  successful: number;
  p50Ms: number;
  p95Ms: number;
  feedbackP95Ms: number;
}

export interface NavigationRateBucket {
  startedAt: number;
  count: number;
}

export const NAVIGATION_RATE_LIMIT_WINDOW_MS = 60_000;
export const NAVIGATION_RATE_LIMIT_SAMPLES = 30;
export const NAVIGATION_RATE_LIMIT_CLIENTS = 4_096;

export function pruneExpiredNavigationRateLimits(
  buckets: Map<string, NavigationRateBucket>,
  now: number,
): number {
  let removed = 0;
  for (const [key, bucket] of buckets) {
    if (now - bucket.startedAt < NAVIGATION_RATE_LIMIT_WINDOW_MS) continue;
    buckets.delete(key);
    removed += 1;
  }
  return removed;
}

export function consumeNavigationRateLimit(
  bucket: NavigationRateBucket | undefined,
  now: number,
): { allowed: boolean; bucket: NavigationRateBucket } {
  const current = !bucket || now - bucket.startedAt >= NAVIGATION_RATE_LIMIT_WINDOW_MS
    ? { startedAt: now, count: 0 }
    : { ...bucket };
  if (current.count >= NAVIGATION_RATE_LIMIT_SAMPLES) return { allowed: false, bucket: current };
  current.count += 1;
  return { allowed: true, bucket: current };
}

const CATALOG_PATHS = new Set([
  '/models',
  '/datasets',
  '/spaces',
  '/skills',
  '/mcps',
  '/prompts',
  '/automations',
  '/benchmarks',
  '/characters',
  '/pages',
]);

export function classifyNavigationRoute(pathname: string): NavigationRouteClass {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (normalized === '/') return 'home';
  if (normalized === '/docs') return 'knowledge-list';
  if (/^\/docs\/[^/]+\/[^/]+$/.test(normalized)) return 'knowledge-detail';
  if (CATALOG_PATHS.has(normalized)) return 'catalog';
  if (normalized === '/new') return 'create';
  if (normalized === '/search') return 'search';
  if (normalized === '/pages/deploy') return 'pages-deploy';
  if (normalized === '/git' || normalized.startsWith('/git/')) return 'forgejo';
  if (/^\/[^/]+\/[^/]+$/.test(normalized)) return 'repository-detail';
  return 'other';
}

export function usesClientNavigation(route: NavigationRouteClass): boolean {
  return route !== 'forgejo' && route !== 'other';
}

export function navigationPathSearch(location: Pick<Location, 'pathname' | 'search'>): string {
  const search = new URLSearchParams(location.search).toString();
  return `${location.pathname}${search ? `?${search}` : ''}`;
}

export function isSameNavigationDestination(
  left: Pick<Location, 'pathname' | 'search'>,
  right: Pick<Location, 'pathname' | 'search'>,
): boolean {
  return navigationPathSearch(left) === navigationPathSearch(right);
}

export function shouldStartHistoryNavigation(
  previousPathSearch: string,
  location: Pick<Location, 'pathname' | 'search'>,
): boolean {
  return previousPathSearch !== navigationPathSearch(location);
}

export function pageHideOutcome(documentNavigation: boolean): NavigationOutcome {
  return documentNavigation ? 'success' : 'cancelled';
}

export function hasCommittedNavigationDestination({
  targetPathSearch,
  currentPathSearch,
}: {
  targetPathSearch: string;
  currentPathSearch: string;
}): boolean {
  return currentPathSearch === targetPathSearch;
}

export function percentile(values: number[], percentileValue: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(sorted.length * percentileValue) - 1),
  );
  return Math.round(sorted[index]);
}

export function summarizeNavigationSamples(
  route: NavigationRouteClass,
  samples: NavigationSample[],
): NavigationSummary {
  const successful = samples.filter((sample) => sample.outcome === 'success');
  return {
    route,
    count: samples.length,
    successful: successful.length,
    p50Ms: percentile(successful.map((sample) => sample.durationMs), 0.5),
    p95Ms: percentile(successful.map((sample) => sample.durationMs), 0.95),
    feedbackP95Ms: percentile(samples.map((sample) => sample.feedbackMs), 0.95),
  };
}

export function isNavigationSample(value: unknown): value is NavigationSample {
  if (!value || typeof value !== 'object') return false;
  const sample = value as Record<string, unknown>;
  return (
    NAVIGATION_ROUTE_CLASSES.includes(sample.route as NavigationRouteClass)
    && typeof sample.durationMs === 'number'
    && Number.isFinite(sample.durationMs)
    && sample.durationMs >= 0
    && sample.durationMs <= 60_000
    && typeof sample.feedbackMs === 'number'
    && Number.isFinite(sample.feedbackMs)
    && sample.feedbackMs >= 0
    && sample.feedbackMs <= 2_000
    && ['success', 'cancelled', 'timeout', 'error'].includes(String(sample.outcome))
    && ['desktop', 'mobile'].includes(String(sample.viewport))
    && ['cold', 'warm'].includes(String(sample.cache))
  );
}

export function normalizeNavigationSample(value: unknown): NavigationSample | null {
  if (!isNavigationSample(value)) return null;
  return {
    route: value.route,
    durationMs: value.durationMs,
    feedbackMs: value.feedbackMs,
    outcome: value.outcome,
    viewport: value.viewport,
    cache: value.cache,
  };
}
