import assert from 'node:assert/strict';
import test from 'node:test';
import { compareRankedRepos, isDefaultCatalogOrdering, paginateRankedRepos, parseCatalogQuery, type RankedRepo } from './catalog-sort';

function repo(id: number, likes: number, views: number, updated: string): RankedRepo {
  return {
    id,
    name: `repo-${id}`,
    full_name: `nyankoface/repo-${id}`,
    description: null,
    owner: { login: 'nyankoface' },
    created_at: `2026-07-${String(id).padStart(2, '0')}T00:00:00Z`,
    updated_at: updated,
    metrics: { owner: 'nyankoface', repo: `repo-${id}`, availability: 'available', likes, views, recent_agents: [] },
  };
}

test('only updated descending keeps category overview mode', () => {
  assert.equal(isDefaultCatalogOrdering('updated', 'desc'), true);
  assert.equal(isDefaultCatalogOrdering('updated', 'asc'), false);
  assert.equal(isDefaultCatalogOrdering('views', 'desc'), false);
  assert.equal(isDefaultCatalogOrdering('likes', 'asc'), false);
});

test('catalog query defaults and validates public API values', () => {
  assert.deepEqual(parseCatalogQuery({}), { sort: 'updated', order: 'desc', page: 1, limit: 48 });
  assert.equal(parseCatalogQuery({ sort: 'likes', order: 'asc', page: '2', limit: '10' }).sort, 'likes');
  assert.throws(() => parseCatalogQuery({ sort: 'stars' }), /Unsupported sort/);
  assert.throws(() => parseCatalogQuery({ order: 'sideways' }), /Unsupported order/);
  assert.throws(() => parseCatalogQuery({ page: '0' }), /positive integer/);
  assert.throws(() => parseCatalogQuery({ limit: '101' }), /between 1 and 100/);
  assert.throws(() => parseCatalogQuery({ topic: 'secret' }), /Unsupported topic/);
});

test('out-of-range pages clamp to the final stable page', () => {
  const items = [1, 2, 3, 4, 5].map((id) => repo(id, 0, 0, `2026-07-0${id}T00:00:00Z`));
  const page = paginateRankedRepos(items, 99, 2);
  assert.equal(page.page, 3);
  assert.equal(page.totalPages, 3);
  assert.deepEqual(page.data.map((item) => item.id), [5]);
});

test('unavailable metrics tie at zero and fall back to deterministic freshness', () => {
  const older = repo(1, 0, 0, '2026-07-01T00:00:00Z');
  const newer = repo(2, 0, 0, '2026-07-02T00:00:00Z');
  older.metrics.availability = 'unavailable';
  newer.metrics.availability = 'unavailable';
  assert.deepEqual([older, newer].sort((a, b) => compareRankedRepos(a, b, 'views', 'asc')).map((item) => item.id), [2, 1]);
});

test('likes and views support both directions', () => {
  const items = [repo(1, 4, 20, '2026-07-01T00:00:00Z'), repo(2, 9, 3, '2026-07-02T00:00:00Z')];
  assert.deepEqual([...items].sort((a, b) => compareRankedRepos(a, b, 'likes', 'desc')).map((item) => item.id), [2, 1]);
  assert.deepEqual([...items].sort((a, b) => compareRankedRepos(a, b, 'likes', 'asc')).map((item) => item.id), [1, 2]);
  assert.deepEqual([...items].sort((a, b) => compareRankedRepos(a, b, 'views', 'desc')).map((item) => item.id), [1, 2]);
  assert.deepEqual([...items].sort((a, b) => compareRankedRepos(a, b, 'views', 'asc')).map((item) => item.id), [2, 1]);
});

test('metric ties use updated, created, and id as stable secondary keys', () => {
  const items = [
    repo(3, 5, 5, '2026-07-01T00:00:00Z'),
    repo(2, 5, 5, '2026-07-02T00:00:00Z'),
    repo(1, 5, 5, '2026-07-02T00:00:00Z'),
  ];
  assert.deepEqual([...items].sort((a, b) => compareRankedRepos(a, b, 'likes', 'desc')).map((item) => item.id), [2, 1, 3]);
});
