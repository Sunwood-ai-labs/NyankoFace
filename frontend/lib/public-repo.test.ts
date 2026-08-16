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
  assert.equal(safePublicUrl('https://[2001:11::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[2001:100::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[2002::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[4000::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[64:ff9b::1]/avatar.png'), 'https://[64:ff9b::1]/avatar.png');
  assert.equal(safePublicUrl('https://[2001:21::1]/avatar.png'), 'https://[2001:21::1]/avatar.png');
  assert.equal(safePublicUrl('https://[2001:3::1]/avatar.png'), 'https://[2001:3::1]/avatar.png');
  assert.equal(safePublicUrl('https://[2001:4:112::1]/avatar.png'), 'https://[2001:4:112::1]/avatar.png');
  assert.equal(safePublicUrl('https://[fec0::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[3fff::1]/avatar.png'), undefined);
  assert.equal(safePublicUrl('https://[64:ff9b:1::1]/avatar.png'), undefined);
});

test('scrubs private origins embedded in retained repository text', () => {
  const original = process.env.FORGEJO_API;
  try {
    process.env.FORGEJO_API = 'https://forgejo.ops.example.com/api/v1';
    const repo = {
      id: 12,
      name: 'demo',
      full_name: 'alice/demo',
      description: 'Docs: http://forgejo.ops.example.com/alice/demo; Encoded: http%3A%2F%2Fforgejo%3A3000%2Falice%2Fdemo; SSH: ssh://git@forgejo:2222/alice/demo.git; SCP: git@forgejo:alice/demo.git; SCP without user: forgejo:alice/demo.git; Bare: forgejo:3000; Private IP: 192.168.1.4:8080; Clock: 12:30 UTC; Image: node:20; Public port: example.com:443; Git: git://forgejo:9418/alice/demo; public: https://8.8.8.8/docs.',
      owner: { login: 'alice' },
      updated_at: '2026-08-16T00:00:00Z',
      created_at: '2026-08-16T12:34:56Z',
    } as Repo;

    const sanitized = sanitizePublicRepo(repo);
    assert.doesNotMatch(sanitized.description || '', /forgejo\.ops\.example\.com/);
    assert.doesNotMatch(sanitized.description || '', /http%3A%2F%2Fforgejo/i);
    assert.doesNotMatch(sanitized.description || '', /ssh:\/\/|git:\/\//);
    assert.doesNotMatch(sanitized.description || '', /git@forgejo:/);
    assert.doesNotMatch(sanitized.description || '', /forgejo:alice\//);
    assert.doesNotMatch(sanitized.description || '', /forgejo:3000/);
    assert.doesNotMatch(sanitized.description || '', /192\.168\.1\.4:8080/);
    assert.match(sanitized.description || '', /12:30 UTC/);
    assert.match(sanitized.description || '', /node:20/);
    assert.match(sanitized.description || '', /example\.com:443/);
    assert.equal(sanitized.updated_at, '2026-08-16T00:00:00Z');
    assert.equal(sanitized.created_at, '2026-08-16T12:34:56Z');
    assert.match(sanitized.description || '', /\[internal URL omitted\]/);
    assert.match(sanitized.description || '', /https:\/\/8\.8\.8\.8\/docs/);
  } finally {
    if (original === undefined) delete process.env.FORGEJO_API;
    else process.env.FORGEJO_API = original;
  }
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

test('rejects private URLs nested in public query and fragment parameters', () => {
  assert.equal(
    safePublicUrl('https://cdn.example.com/images//avatar.png'),
    'https://cdn.example.com/images//avatar.png',
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect?next=http://forgejo:3000/app'),
    undefined,
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect?next=http%3A%2F%2Fforgejo%3A3000%2Fapp'),
    undefined,
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect#next=https%3A%2F%2F127.0.0.1%2Fapp'),
    undefined,
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect/http://forgejo:3000/app'),
    undefined,
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect?bad=%E0%A4%A&next=http%3A%2F%2Fforgejo%3A3000%2Fapp'),
    undefined,
  );
  assert.equal(
    safePublicUrl('https://public.example/redirect?next=https://cdn.example/app'),
    'https://public.example/redirect?next=https://cdn.example/app',
  );
  assert.equal(
    safePublicUrl(
      'https://public.example/redirect?next=https%3A%2F%2Fpublic1.example%2F%3Fnext%3Dhttps%253A%252F%252Fpublic2.example%252F%253Fnext%253Dhttps%25253A%25252F%25252Fpublic3.example%25252F%25253Fnext%25253Dhttp%25253A%25252F%25252Fforgejo%25253A3000%25252Fapp',
    ),
    undefined,
  );
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
  assert.equal(safePublicUrl('https://192.88.99.2/avatar.png'), 'https://192.88.99.2/avatar.png');
  assert.equal(safePublicUrl('https://alice:secret@public.example/avatar.png'), undefined);
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
