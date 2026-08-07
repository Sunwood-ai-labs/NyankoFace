import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import {
  fillRecentPagesReservation,
  mergeHomePagesRepositories,
  resolveHomePagesState,
  selectPublishedPages,
  type InspectedPageCandidate,
} from './pages-discovery';

function candidate(
  id: number,
  status: 'published' | 'missing' | 'private' | 'error',
  updatedAt: string,
  source: 'gh-pages' | 'docs' | null = null,
): InspectedPageCandidate {
  const name = `site-${id}`;
  return {
    owner: 'nyankoface',
    repo: {
      id,
      name,
      full_name: `nyankoface/${name}`,
      description: `Site ${id}`,
      owner: { login: 'nyankoface' },
      updated_at: updatedAt,
    },
    inspection: {
      owner: 'nyankoface',
      repo: name,
      public: true,
      default_branch: 'main',
      status,
      source,
      source_ref: source === 'gh-pages' ? 'gh-pages' : source === 'docs' ? 'main' : null,
      directory_prefix: source === 'docs' ? 'docs' : source === 'gh-pages' ? '' : null,
      index_path: source === 'docs' ? 'docs/index.html' : source === 'gh-pages' ? 'index.html' : null,
      public_url: status === 'published' ? `https://hub.example/pages/nyankoface/${name}/` : null,
      checks: [],
      reasons: [],
    },
  };
}

test('published Pages are filtered, ordered by freshness, and limited', () => {
  const candidates = [
    candidate(1, 'published', '2026-07-01T00:00:00Z', 'docs'),
    candidate(2, 'missing', '2026-07-05T00:00:00Z'),
    candidate(3, 'published', '2026-07-03T00:00:00Z', 'gh-pages'),
  ];
  const metrics = {
    'nyankoface/site-3': { owner: 'nyankoface', repo: 'site-3', availability: 'available' as const, views: 8, likes: 2, recent_agents: [] },
  };
  const result = selectPublishedPages(candidates, metrics, 1);
  assert.equal(result.length, 1);
  assert.equal(result[0].repo.name, 'site-3');
  assert.equal(result[0].publicUrl, 'https://hub.example/pages/nyankoface/site-3/');
  assert.equal(result[0].metrics.views, 8);
});

test('missing metrics remain explicit instead of rendering invented counts', () => {
  const [result] = selectPublishedPages([
    candidate(1, 'published', '2026-07-01T00:00:00Z', 'docs'),
  ], {});
  assert.equal(result.metrics.availability, 'unavailable');
  assert.equal(result.metrics.likes, 0);
});

test('indexed Pages are prioritized while topic-less recent repositories remain eligible', () => {
  const indexed = candidate(1, 'published', '2026-07-01T00:00:00Z', 'docs').repo;
  indexed.topics = ['pages'];
  const untagged = candidate(2, 'published', '2026-07-02T00:00:00Z', 'gh-pages').repo;
  untagged.topics = [];
  const duplicate = { ...indexed };
  assert.deepEqual(
    mergeHomePagesRepositories([indexed], [untagged, duplicate], 3).map((repo) => repo.full_name),
    ['nyankoface/site-1', 'nyankoface/site-2'],
  );
});

test('topic-less repositories retain reserved inspection slots when the index is full', () => {
  const indexed = Array.from({ length: 13 }, (_, index) => (
    candidate(index + 1, 'published', `2026-07-${String(index + 1).padStart(2, '0')}T00:00:00Z`, 'docs').repo
  ));
  const untagged = candidate(99, 'published', '2026-07-31T00:00:00Z', 'gh-pages').repo;
  const result = mergeHomePagesRepositories(indexed, [indexed[0], untagged], 12);
  assert.equal(result.length, 12);
  assert.equal(result.some((repo) => repo.full_name === untagged.full_name), true);
});

test('all four recent reservations survive the inspection-limit boundary', () => {
  const indexed = Array.from({ length: 9 }, (_, index) => (
    candidate(index + 1, 'published', `2026-07-${String(index + 1).padStart(2, '0')}T00:00:00Z`, 'docs').repo
  ));
  const recent = Array.from({ length: 4 }, (_, index) => (
    candidate(index + 20, 'published', `2026-07-${String(index + 20).padStart(2, '0')}T00:00:00Z`, 'gh-pages').repo
  ));
  const result = mergeHomePagesRepositories(indexed, recent, 12);
  assert.equal(result.length, 12);
  assert.deepEqual(
    recent.map((repo) => repo.full_name).filter((name) => result.some((repo) => repo.full_name === name)),
    recent.map((repo) => repo.full_name),
  );
});

test('recent discovery paginates past an indexed-only first page to fill unique fallback slots', async () => {
  const indexed = Array.from({ length: 13 }, (_, index) => (
    candidate(index + 1, 'published', `2026-07-${String(index + 1).padStart(2, '0')}T00:00:00Z`, 'docs').repo
  ));
  const untagged = Array.from({ length: 4 }, (_, index) => (
    candidate(index + 30, 'published', `2026-07-${String(index + 20).padStart(2, '0')}T00:00:00Z`, 'gh-pages').repo
  ));
  const requestedPages: number[] = [];
  const result = await fillRecentPagesReservation(
    indexed,
    { ok: true, data: indexed, total_count: 17 },
    async (page) => {
      requestedPages.push(page);
      return { ok: true, data: untagged, total_count: 17 };
    },
  );

  assert.deepEqual(requestedPages, [2]);
  assert.deepEqual(
    mergeHomePagesRepositories(indexed, result.data, 12)
      .filter((repo) => untagged.some((candidateRepo) => candidateRepo.full_name === repo.full_name))
      .map((repo) => repo.full_name),
    untagged.map((repo) => repo.full_name),
  );
});

test('tagged repositories on later pages do not consume topic-less fallback slots', async () => {
  const indexed = Array.from({ length: 13 }, (_, index) => {
    const repo = candidate(index + 1, 'published', `2026-07-${String(index + 1).padStart(2, '0')}T00:00:00Z`, 'docs').repo;
    repo.topics = ['pages'];
    return repo;
  });
  const laterTagged = Array.from({ length: 13 }, (_, index) => {
    const repo = candidate(index + 20, 'published', '2026-07-20T00:00:00Z', 'docs').repo;
    repo.topics = ['pages'];
    return repo;
  });
  const untagged = Array.from({ length: 4 }, (_, index) => {
    const repo = candidate(index + 40, 'published', '2026-07-21T00:00:00Z', 'gh-pages').repo;
    repo.topics = [];
    return repo;
  });
  const requestedPages: number[] = [];
  const result = await fillRecentPagesReservation(
    indexed,
    { ok: true, data: indexed, total_count: 30 },
    async (page) => {
      requestedPages.push(page);
      return {
        ok: true,
        data: page === 2 ? laterTagged : untagged,
        total_count: 30,
      };
    },
  );

  assert.deepEqual(requestedPages, [2, 3]);
  const merged = mergeHomePagesRepositories(indexed, result.data, 12);
  assert.deepEqual(
    merged.filter((repo) => untagged.some((candidateRepo) => candidateRepo.full_name === repo.full_name))
      .map((repo) => repo.full_name),
    untagged.map((repo) => repo.full_name),
  );
});

test('a later recent-page failure retains candidates accumulated from successful pages', async () => {
  const indexed = Array.from({ length: 13 }, (_, index) => (
    candidate(index + 1, 'published', '2026-07-01T00:00:00Z', 'docs').repo
  ));
  const untagged = candidate(50, 'published', '2026-07-31T00:00:00Z', 'gh-pages').repo;
  untagged.topics = [];
  const result = await fillRecentPagesReservation(
    indexed,
    { ok: true, data: [...indexed, untagged], total_count: 30 },
    async () => ({ ok: false, data: [], total_count: 0 }),
  );

  assert.equal(result.ok, false);
  assert.equal(result.data.some((repo) => repo.full_name === untagged.full_name), true);
  assert.equal(
    mergeHomePagesRepositories(indexed, result.data, 12)
      .some((repo) => repo.full_name === untagged.full_name),
    true,
  );
});

test('recent fallback pagination stops at the request-count cap', async () => {
  const indexed = Array.from({ length: 13 }, (_, index) => (
    candidate(index + 1, 'published', '2026-07-01T00:00:00Z', 'docs').repo
  ));
  const requestedPages: number[] = [];
  await fillRecentPagesReservation(
    indexed,
    { ok: true, data: indexed, total_count: 1_000 },
    async (page) => {
      requestedPages.push(page);
      const tagged = Array.from({ length: 13 }, (_, index) => {
        const repo = candidate(page * 100 + index, 'published', '2026-07-01T00:00:00Z', 'docs').repo;
        repo.topics = ['pages'];
        return repo;
      });
      return { ok: true, data: tagged, total_count: 1_000 };
    },
  );

  assert.deepEqual(requestedPages, [2, 3, 4]);
});

test('home state distinguishes empty data from upstream failure', () => {
  assert.equal(resolveHomePagesState(false, [], []), 'unavailable');
  assert.equal(resolveHomePagesState(true, [], []), 'empty');
  assert.equal(resolveHomePagesState(true, [candidate(1, 'missing', '2026-07-01T00:00:00Z')], []), 'empty');
  assert.equal(resolveHomePagesState(true, [candidate(1, 'error', '2026-07-01T00:00:00Z')], []), 'unavailable');
  assert.equal(resolveHomePagesState(true, [
    candidate(1, 'missing', '2026-07-02T00:00:00Z'),
    candidate(2, 'error', '2026-07-01T00:00:00Z'),
  ], []), 'unavailable');
  assert.equal(resolveHomePagesState(true, [candidate(1, 'missing', '2026-07-01T00:00:00Z')], [], true), 'unavailable');
});

test('home Pages discovery keeps browse, publish, public-site, and accessible navigation contracts distinct', () => {
  const source = readFileSync(new URL('../components/HomePagesShowcase.tsx', import.meta.url), 'utf8');
  assert.match(source, /href="\/pages"/);
  assert.match(source, /href="\/pages\/deploy"/);
  assert.match(source, /href=\{publicUrl\}/);
  assert.match(source, /aria-labelledby="home-pages-title"/);
  assert.match(source, /aria-label=\{ui\(locale, 'Pagesの閲覧と公開'/);
  assert.match(source, /Pagesは、ドキュメントやポートフォリオなどの静的サイト/);
  assert.match(source, /Spacesは、GradioやDockerなど実行中のAIアプリ/);
  assert.match(source, /data-home-pages-state=\{preview.state\}/);
  assert.match(source, /`Likes \$\{metrics.likes\}`/);
  assert.match(source, /'Likes unavailable'/);
  assert.match(source, /`Views \$\{metrics.views\}`/);
  assert.match(source, /'Views unavailable'/);
});

test('home Pages discovery reserves inspection time within its total latency budget', () => {
  const source = readFileSync(new URL('./pages-discovery.ts', import.meta.url), 'utf8');
  assert.match(source, /topic: 'pages'/);
  assert.match(source, /mergeHomePagesRepositories/);
  assert.equal(source.match(/searchRepos\(\{/g)?.length, 3);
  assert.match(source, /HOME_PAGES_INSPECTION_LIMIT = 12/);
  assert.match(source, /HOME_PAGES_RECENT_RESERVATION = 4/);
  assert.match(source, /HOME_PAGES_SEARCH_LIMIT = HOME_PAGES_INSPECTION_LIMIT \+ 1/);
  assert.match(source, /HOME_PAGES_MAX_SEARCH_PAGES = 4/);
  assert.match(source, /HOME_PAGES_SEARCH_BUDGET_MS = 900/);
  assert.match(source, /HOME_PAGES_LOAD_BUDGET_MS = 1_500/);
  assert.match(source, /AbortSignal\.any\(\[/);
  assert.match(source, /AbortSignal\.timeout\(HOME_PAGES_SEARCH_BUDGET_MS\)/);
  assert.match(source, /page: 1/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /fillRecentPagesReservation/);
  assert.match(source, /const availableRecent = recentRepositories\.data/);
});
