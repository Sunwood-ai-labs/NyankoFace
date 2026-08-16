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
    website: 'http://forgejo:3000/alice/demo',
    url: 'http://forgejo:3000/api/v1/repos/alice/demo',
    languages_url: 'http://forgejo:3000/api/v1/repos/alice/demo/languages',
    clone_url: 'http://localhost:3000/alice/demo.git',
    ssh_url: 'ssh://git@localhost:2222/alice/demo.git',
    space_url: 'https://[fc00::1]:8443/spaces/alice/demo',
    parent: {
      full_name: 'alice/parent',
      html_url: 'http://forgejo:3000/alice/parent',
      clone_url: 'http://forgejo:3000/alice/parent.git',
      website: 'http://forgejo:3000/alice/parent/docs',
    },
    external_tracker: {
      external_tracker_format: 'http://forgejo:3000/{user}/{repo}/issues/{index}',
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
  assert.equal((sanitized as Repo & Record<string, unknown>).website, undefined);
  assert.equal((sanitized as Repo & Record<string, unknown>).external_tracker, undefined);
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
  assert.equal(safePublicUrl('https://[ff05::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[2001:db8::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[fec0::1]/avatar.png'), undefined);
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

test('rejects internal hostnames and preserves public service labels', () => {
  assert.equal(safePublicUrl('https://git/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://forgejo.:3000/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://nas.home.arpa/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://198.18.0.1/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://0.1.2.3/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://192.0.1.1/avatar.png'), 'https://192.0.1.1/avatar.png');
  assert.equal(safePublicUrl('https://192.0.0.9/avatar.png'), 'https://192.0.0.9/avatar.png');
  assert.equal(safePublicUrl('https://192.0.0.10/avatar.png'), 'https://192.0.0.10/avatar.png');
  assert.equal(safePublicUrl('https://git.example.com/avatar.png'), 'https://git.example.com/avatar.png');
  assert.equal(safePublicUrl('https://gateway.example.org/avatar.png'), 'https://gateway.example.org/avatar.png');
  assert.equal(safePublicUrl('https://frontend.example.net/avatar.png'), 'https://frontend.example.net/avatar.png');
  assert.equal(safePublicUrl('https://forgejo.example.com/avatar.png'), 'https://forgejo.example.com/avatar.png');
  assert.equal(safePublicUrl('https://backend.example.com/avatar.png'), 'https://backend.example.com/avatar.png');
  assert.equal(safePublicUrl('https://mcp.example.com/avatar.png'), 'https://mcp.example.com/avatar.png');
});

test('rejects the configured Forgejo origin even when its hostname is public-looking', () => {
  const original = process.env.FORGEJO_API;
  try {
    process.env.FORGEJO_API = 'https://forgejo.ops.example.com/api/v1';
    assert.equal(safePublicUrl('https://forgejo.ops.example.com/avatar.png'), undefined);
    process.env.FORGEJO_API = 'https://[2606:4700:4700::1111]/api/v1';
    assert.equal(safePublicUrl('https://[2606:4700:4700::1111]/avatar.png'), undefined);
  } finally {
    if (original === undefined) delete process.env.FORGEJO_API;
    else process.env.FORGEJO_API = original;
  }
});
