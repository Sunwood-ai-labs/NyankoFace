import assert from 'node:assert/strict';
import test from 'node:test';
import { getRepo, searchAllReposByTopicAndQuery, searchRepos, SKILL_MAX_BYTES, type Repo } from './forgejo';

const SKILL_CONTENT = '# Example Skill\n\nUse this skill for the regression test.\n';

function repo(name: string, isPrivate = false): Repo {
  return {
    id: name.length,
    name,
    full_name: `owner/${name}`,
    description: 'A test skill',
    owner: { login: 'owner' },
    updated_at: '2026-08-18T00:00:00Z',
    default_branch: 'main',
    private: isPrivate,
    topics: ['skill'],
  };
}

function skillRootEntry(content: string = SKILL_CONTENT) {
  const bytes = Buffer.from(content, 'utf-8');
  return {
    name: 'SKILL.md',
    path: 'SKILL.md',
    type: 'file',
    size: bytes.byteLength,
    sha: 'a'.repeat(40),
    encoding: 'base64',
    content: bytes.toString('base64'),
  };
}

function jsonResponse(value: unknown, status = 200, headers?: Record<string, string>) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

async function withFetch(
  handler: (url: URL) => Response | Promise<Response>,
  callback: () => Promise<void>,
) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input) => handler(new URL(String(input)))) as typeof fetch;
  try {
    await callback();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test('admits a public Skill with a readable root SKILL.md and keeps detail enrichment consistent', async () => {
  const candidate = repo('valid-skill');
  const rootRequests: string[] = [];
  await withFetch(async (url) => {
    if (url.pathname.endsWith('/repos/search')) {
      return jsonResponse({ data: [candidate] }, 200, { 'x-total-count': '1' });
    }
    if (url.pathname.endsWith('/contents/SKILL.md')) {
      rootRequests.push(url.pathname);
      return jsonResponse(skillRootEntry());
    }
    if (url.pathname.endsWith('/contents/skill.json')) return jsonResponse({}, 404);
    if (url.pathname.endsWith('/repos/owner/valid-skill')) return jsonResponse(candidate);
    throw new Error(`Unexpected Forgejo request: ${url}`);
  }, async () => {
    const listing = await searchRepos({ topic: 'skill', limit: 10 });
    assert.equal(listing.ok, true);
    assert.deepEqual(listing.data.map((item) => item.full_name), ['owner/valid-skill']);
    assert.deepEqual(listing.data[0].skill_relationships, { schemaVersion: 2, dependencies: [] });

    const detail = await getRepo('owner', 'valid-skill');
    assert.equal(detail?.full_name, 'owner/valid-skill');
    assert.deepEqual(detail?.skill_relationships, { schemaVersion: 2, dependencies: [] });
  });
  assert.equal(rootRequests.length, 2);
});

test('rejects a Skill whose root SKILL.md is missing from both catalog and detail', async () => {
  const candidate = repo('missing-root');
  await withFetch(async (url) => {
    if (url.pathname.endsWith('/repos/search')) return jsonResponse({ data: [candidate] }, 200, { 'x-total-count': '1' });
    if (url.pathname.endsWith('/contents/SKILL.md')) return jsonResponse({ message: 'not found' }, 404);
    if (url.pathname.endsWith('/repos/owner/missing-root')) return jsonResponse(candidate);
    throw new Error(`Unexpected Forgejo request: ${url}`);
  }, async () => {
    const listing = await searchAllReposByTopicAndQuery('skill');
    assert.equal(listing.ok, true);
    assert.deepEqual(listing.data, []);
    assert.equal(listing.total_count, 0);
    assert.equal(await getRepo('owner', 'missing-root'), null);
  });
});

test('reports root-content upstream failure as unavailable instead of deleting the catalog', async () => {
  const candidate = repo('temporarily-unavailable');
  await withFetch(async (url) => {
    if (url.pathname.endsWith('/repos/search')) return jsonResponse({ data: [candidate] }, 200, { 'x-total-count': '1' });
    if (url.pathname.endsWith('/contents/SKILL.md')) return jsonResponse({ message: 'try again' }, 503);
    throw new Error(`Unexpected Forgejo request: ${url}`);
  }, async () => {
    const listing = await searchRepos({ topic: 'skill' });
    assert.deepEqual(listing, { ok: false, data: [], total_count: 0 });
  });
});

test('fails closed for oversized and malformed root content', async () => {
  const cases = [
    {
      name: 'oversized',
      entry: { ...skillRootEntry(), size: SKILL_MAX_BYTES + 1 },
    },
    {
      name: 'malformed',
      entry: { ...skillRootEntry(), content: 'not-valid-base64' },
    },
    {
      name: 'malformed-response',
      entry: null,
    },
    {
      name: 'malformed-encoding',
      entry: { ...skillRootEntry(), encoding: 7 },
    },
  ];

  for (const current of cases) {
    const candidate = repo(`${current.name}-root`);
    await withFetch(async (url) => {
      if (url.pathname.endsWith('/repos/search')) return jsonResponse({ data: [candidate] });
      if (url.pathname.endsWith('/contents/SKILL.md')) return jsonResponse(current.entry);
      throw new Error(`Unexpected Forgejo request: ${url}`);
    }, async () => {
      const listing = await searchRepos({ topic: 'skill' });
      assert.equal(listing.ok, true, current.name);
      assert.deepEqual(listing.data, [], current.name);
    });
  }
});

test('keeps private Skill repositories outside root validation and the public catalog', async () => {
  const candidate = repo('private-skill', true);
  let rootRead = false;
  await withFetch(async (url) => {
    if (url.pathname.endsWith('/repos/search')) return jsonResponse({ data: [candidate] });
    if (url.pathname.endsWith('/contents/SKILL.md')) {
      rootRead = true;
      return jsonResponse(skillRootEntry());
    }
    if (url.pathname.endsWith('/repos/owner/private-skill')) return jsonResponse(candidate);
    throw new Error(`Unexpected Forgejo request: ${url}`);
  }, async () => {
    const listing = await searchRepos({ topic: 'skill' });
    assert.equal(listing.ok, true);
    assert.deepEqual(listing.data, []);
    assert.equal(await getRepo('owner', 'private-skill'), null);
  });
  assert.equal(rootRead, false);
});
