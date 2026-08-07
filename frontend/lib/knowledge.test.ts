import assert from 'node:assert/strict';
import test from 'node:test';

import { matchesKnowledgeRepositoryIdentity } from './knowledge';

test('cached knowledge remains bound to the originating Forgejo repository ID', () => {
  const article = {
    owner: 'nyankoface',
    repository: 'release-notes',
    repositoryId: 42,
  };

  assert.equal(matchesKnowledgeRepositoryIdentity(article, {
    id: 42,
    full_name: 'nyankoface/release-notes',
  }), true);
  assert.equal(matchesKnowledgeRepositoryIdentity(article, {
    id: 99,
    full_name: 'nyankoface/release-notes',
  }), false);
  assert.equal(matchesKnowledgeRepositoryIdentity(article, {
    id: 42,
    full_name: 'nyankoface/renamed-release-notes',
  }), false);
});
