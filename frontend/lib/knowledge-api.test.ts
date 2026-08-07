import assert from 'node:assert/strict';
import test from 'node:test';
import { knowledgeResponseHeaders } from './knowledge-api';

test('knowledge responses require visibility revalidation before cache reuse', () => {
  const headers = knowledgeResponseHeaders({ repositoryId: 1, updatedAt: '2026-08-01', bodyMarkdown: 'one' });
  assert.equal(headers['Cache-Control'], 'public, no-cache, must-revalidate');
  assert.doesNotMatch(headers['Cache-Control'], /max-age=[1-9]/);
});

test('knowledge ETags change when the returned representation changes', () => {
  const first = knowledgeResponseHeaders({ repositoryId: 1, updatedAt: '2026-08-01', bodyMarkdown: 'one' });
  const second = knowledgeResponseHeaders({ repositoryId: 1, updatedAt: '2026-08-01', bodyMarkdown: 'two' });
  assert.notEqual(first.ETag, second.ETag);
  assert.match(first.ETag, /^"sha256-[a-f0-9]{64}"$/);
});
