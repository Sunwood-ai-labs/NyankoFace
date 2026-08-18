import assert from 'node:assert/strict';
import test from 'node:test';
import { searchRepos } from './forgejo';

test('separates the public result count from the privileged upstream count', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    data: [
      {
        id: 1,
        name: 'public-model',
        full_name: 'alice/public-model',
        description: null,
        owner: { login: 'alice' },
        updated_at: '2026-08-18T00:00:00Z',
        private: false,
      },
      {
        id: 2,
        name: 'private-model',
        full_name: 'alice/private-model',
        description: null,
        owner: { login: 'alice' },
        updated_at: '2026-08-18T00:00:00Z',
        private: true,
      },
    ],
  }), {
    status: 200,
    headers: { 'content-type': 'application/json', 'x-total-count': '3' },
  });

  try {
    const result = await searchRepos({ topic: 'model', limit: 2, page: 1 });
    assert.equal(result.ok, true);
    assert.equal(result.data.length, 1);
    assert.equal(result.total_count, 1);
    assert.equal(result.upstream_total_count, 3);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
