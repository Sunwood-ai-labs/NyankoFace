import assert from 'node:assert/strict';
import test from 'node:test';
import { safePublicUrl, sanitizePublicRepo } from './public-repo';
import type { Repo } from './forgejo';

test('sanitizes upstream repository URLs at the public boundary', () => {
  const raw = {
    id: 7,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: {
      login: 'alice',
      html_url: 'http://forgejo:3000/alice',
      avatar_url: 'http://forgejo:3000/user/avatar/alice',
    },
    updated_at: '2026-08-16T00:00:00Z',
    html_url: 'http://192.168.11.22:8443/git/alice/demo',
    url: 'http://forgejo:3000/api/v1/repos/alice/demo',
    languages_url: 'http://forgejo:3000/api/v1/repos/alice/demo/languages',
    clone_url: 'http://localhost:3000/alice/demo.git',
    ssh_url: 'ssh://git@localhost:2222/alice/demo.git',
    space_url: 'https://[fc00::1]:8443/spaces/alice/demo',
    parent: {
      full_name: 'alice/parent',
      html_url: 'http://forgejo:3000/alice/parent',
      clone_url: 'http://forgejo:3000/alice/parent.git',
    },
  } as unknown as Repo & Record<string, unknown>;

  const sanitized = sanitizePublicRepo(raw);
  const serialized = JSON.stringify(sanitized);

  assert.equal(sanitized.html_url, '/git/alice/demo');
  assert.equal(sanitized.owner.avatar_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).clone_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).ssh_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).languages_url, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).space_url, undefined);
  const parent = (sanitized as Repo & Record<string, unknown>).parent as Record<string, unknown>;
  assert.equal(parent.html_url, undefined);
  assert.equal(parent.clone_url, undefined);
  assert.equal((sanitized.owner as unknown as Record<string, unknown>).html_url, undefined);
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

test('rejects protocol-relative avatar URLs that could target an internal host', () => {
  const repo = {
    id: 9,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: { login: 'alice', avatar_url: '//forgejo:3000/user/avatar/alice' },
    updated_at: '2026-08-16T00:00:00Z',
  } as unknown as Repo;

  assert.equal(sanitizePublicRepo(repo).owner.avatar_url, undefined);
});

test('rejects link-local and IPv6 ULA origins', () => {
  const repo = {
    id: 10,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: { login: 'alice', avatar_url: 'https://[fe80::1]/avatar.png' },
    updated_at: '2026-08-16T00:00:00Z',
  } as unknown as Repo;

  assert.equal(sanitizePublicRepo(repo).owner.avatar_url, undefined);
});

test('rejects hex IPv4-mapped IPv6 and backslash-normalized internal URLs', () => {
  const repo = {
    id: 11,
    name: 'demo',
    full_name: 'alice/demo',
    description: null,
    owner: {
      login: 'alice',
      avatar_url: 'https://[::ffff:0a00:0001]/avatar.png',
    },
    updated_at: '2026-08-16T00:00:00Z',
  } as unknown as Repo;

  assert.equal(sanitizePublicRepo(repo).owner.avatar_url, undefined);
  assert.equal(safePublicUrl('/\\\\forgejo:3000/private'), undefined);
});
