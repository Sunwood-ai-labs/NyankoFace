import assert from 'node:assert/strict';
import test from 'node:test';
import { sanitizePublicRepo } from './public-repo';
import type { Repo } from './forgejo';

test('sanitizes upstream repository URLs at the public boundary', () => {
  const raw = {
    id: 7,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: {
      login: 'alice',
      avatar_url: 'http://forgejo:3000/user/avatar/alice',
    },
    updated_at: '2026-08-16T00:00:00Z',
    html_url: 'http://192.168.11.22:8443/git/alice/demo',
    url: 'http://forgejo:3000/api/v1/repos/alice/demo',
    clone_url: 'http://localhost:3000/alice/demo.git',
    ssh_url: 'ssh://git@localhost:2222/alice/demo.git',
  } as unknown as Repo & Record<string, unknown>;

  const sanitized = sanitizePublicRepo(raw);
  const serialized = JSON.stringify(sanitized);

  assert.equal(sanitized.html_url, '/git/alice/demo');
  assert.equal(sanitized.owner.avatar_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).clone_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).ssh_url, undefined);
  assert.doesNotMatch(serialized, /192\.168\.11\.22|forgejo:3000|localhost:3000|ssh:\/\//);
});

test('keeps public relative avatar paths usable', () => {
  const repo = {
    id: 8,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: { login: 'alice', avatar_url: '/git/avatars/alice.png' },
    updated_at: '2026-08-16T00:00:00Z',
  } as Repo;

  assert.equal(sanitizePublicRepo(repo).owner.avatar_url, '/git/avatars/alice.png');
});
