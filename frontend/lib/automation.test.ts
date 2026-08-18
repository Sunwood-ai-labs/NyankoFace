import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDisabledAutomationBundle, inspectAutomationToml } from './automation';
import {
  getPublicTextFileAtRevision,
  resolvePublicRepoRevision,
} from './forgejo';

const validToml = `
schema_version = 1
name = "Weekly repository report"
description = "Summarize repository activity without changing files."
platform = "codex"
format = "automation"
version = "1.0.0"
schedule_type = "weekly"
timezone = "Asia/Tokyo"
trigger = "Every Monday at 09:00"
required_permissions = ["repository:read"]
required_connectors = ["github"]
workspace_required = false
delivery_type = "none"
tested_on = ["Codex Desktop"]
tags = ["report", "repository"]
license = "MIT"
enabled = false
required_secrets = ["GITHUB_TOKEN"]
`;

test('accepts a safe disabled Automation and creates a disabled bundle', () => {
  const result = inspectAutomationToml(validToml, {
    owner: 'nyankoface',
    repo: 'weekly-repository-report',
    ref: 'v1.0.0',
    sha: 'abc123',
  });
  assert.equal(result.ok, true);
  assert.equal(result.compatible, true);
  assert.equal(result.importState, 'disabled');
  assert.equal(result.config?.required_permissions[0], 'repository:read');
  assert.match(result.sourceHash, /^[a-f0-9]{64}$/);
  const bundle = buildDisabledAutomationBundle(result);
  assert.match(bundle, /enabled = false/);
  assert.match(bundle, /required_secrets = \[\s*"GITHUB_TOKEN"\s*\]/);
});

test('rejects missing fields and unsupported schema versions', () => {
  const result = inspectAutomationToml('schema_version = 9\nname = "Broken"\n');
  assert.equal(result.ok, false);
  assert.ok(result.findings.some((item) => item.code === 'unsupported_schema'));
  assert.ok(result.findings.some((item) => item.code === 'missing_field'));
});

test('rejects embedded secrets, email, private URLs, absolute paths, and destructive commands', () => {
  const unsafe = `${validToml}
token = "ghp_real_secret_value"
notes = "Send mail to admin@example.com, then call http://127.0.0.1/hook from C:\\\\Users\\\\alice and run rm -rf /."
`;
  const result = inspectAutomationToml(unsafe);
  const codes = new Set(result.findings.map((item) => item.code));
  assert.equal(result.ok, false);
  assert.ok(codes.has('unknown_field'));
  assert.ok(codes.has('embedded_secret'));
  assert.ok(codes.has('email_address'));
  assert.ok(codes.has('private_url'));
  assert.ok(codes.has('absolute_path'));
  assert.ok(codes.has('destructive_command'));
});

test('rejects enabled public packages and unknown fields', () => {
  const result = inspectAutomationToml(
    validToml.replace('enabled = false', 'enabled = true') + '\ncommand = "echo hello"\n',
  );
  assert.equal(result.ok, false);
  assert.ok(result.findings.some((item) => item.code === 'enabled_public_config'));
  assert.ok(result.findings.some((item) => item.code === 'unknown_field'));
});

test('warns when external delivery or another runtime requires confirmation', () => {
  const result = inspectAutomationToml(
    validToml
      .replace('platform = "codex"', 'platform = "other-runtime"')
      .replace('delivery_type = "none"', 'delivery_type = "channel"'),
  );
  assert.equal(result.ok, true);
  assert.equal(result.compatible, false);
  assert.ok(result.findings.some((item) => item.code === 'external_delivery'));
  assert.ok(result.findings.some((item) => item.code === 'runtime_compatibility'));
  assert.throws(() => buildDisabledAutomationBundle(result), /warnings must be acknowledged/);
  assert.match(
    buildDisabledAutomationBundle(result, { acknowledgeWarnings: true }),
    /enabled = false/,
  );
});

test('does not expose malformed TOML or credential values in findings', () => {
  const secret = 'ghp_never_echo_this_value';
  const result = inspectAutomationToml(`name = "${secret}\n`);
  const serialized = JSON.stringify(result.findings);
  assert.equal(result.ok, false);
  assert.ok(result.findings.some((item) => item.code === 'invalid_toml'));
  assert.doesNotMatch(serialized, /never_echo_this_value/);
});

test('rejects bearer tokens, private keys, and credential URLs without echoing them', () => {
  const unsafe = validToml.replace(
    'description = "Summarize repository activity without changing files."',
    'description = "Bearer abcdefghijklmnopqrstuvwxyz https://user:password@example.com/"',
  );
  const result = inspectAutomationToml(unsafe);
  assert.equal(result.ok, false);
  assert.ok(result.findings.some((item) => item.code === 'embedded_secret'));
  assert.doesNotMatch(JSON.stringify(result.findings), /abcdefghijklmnopqrstuvwxyz|password/);
});

test('rejects oversized Automation files before parsing', () => {
  const result = inspectAutomationToml(`notes = "${'a'.repeat(256 * 1024)}"`);
  assert.equal(result.ok, false);
  assert.deepEqual(result.findings.map((item) => item.code), ['file_too_large']);
});

test('public revision lookup never sends the privileged Forgejo token', async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; authorization: string | null }> = [];
  let call = 0;
  globalThis.fetch = (async (input, init) => {
    requests.push({
      url: String(input),
      authorization: new Headers(init?.headers).get('authorization'),
    });
    call += 1;
    if (call === 1) {
      return Response.json({
        id: 1,
        name: 'weekly-report',
        full_name: 'nyankoface/weekly-report',
        description: 'Safe report',
        owner: { login: 'nyankoface' },
        updated_at: new Date(0).toISOString(),
        private: false,
        default_branch: 'main',
        topics: ['automation'],
      });
    }
    return Response.json({ sha: 'a'.repeat(40) });
  }) as typeof fetch;
  try {
    const revision = await resolvePublicRepoRevision('nyankoface', 'weekly-report');
    assert.equal(revision?.sha, 'a'.repeat(40));
    assert.equal(requests.length, 2);
    assert.ok(requests.every((request) => request.authorization === null));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('public revision lookup uses the raw default branch before repository sanitization', async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  let call = 0;
  globalThis.fetch = (async (input) => {
    requests.push(String(input));
    call += 1;
    if (call === 1) {
      return Response.json({
        id: 2,
        name: 'unsafe-ref',
        full_name: 'nyankoface/unsafe-ref',
        description: 'Safe report',
        owner: { login: 'nyankoface' },
        updated_at: new Date(0).toISOString(),
        private: false,
        default_branch: 'http://forgejo:3000/main',
        topics: ['automation'],
      });
    }
    return Response.json({ sha: 'c'.repeat(40) });
  }) as typeof fetch;
  try {
    const revision = await resolvePublicRepoRevision('nyankoface', 'unsafe-ref');
    assert.equal(revision?.requestedRef, 'http://forgejo:3000/main');
    assert.match(requests[1], /git\/commits\/http%3A%2F%2Fforgejo%3A3000%2Fmain$/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('private repositories are indistinguishable from missing public revisions', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => Response.json({ private: true })) as typeof fetch;
  try {
    assert.equal(await resolvePublicRepoRevision('private-owner', 'private-repo'), null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('public Automation content is pinned to the reviewed SHA', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = (async (input) => {
    requestedUrl = String(input);
    return Response.json({
      name: 'automation.toml',
      path: 'automation.toml',
      type: 'file',
      size: Buffer.byteLength(validToml),
      sha: 'b'.repeat(40),
      encoding: 'base64',
      content: Buffer.from(validToml).toString('base64'),
    });
  }) as typeof fetch;
  try {
    const content = await getPublicTextFileAtRevision(
      'nyankoface',
      'weekly-report',
      'automation.toml',
      'b'.repeat(40),
    );
    assert.equal(content, validToml);
    assert.match(requestedUrl, new RegExp(`ref=${'b'.repeat(40)}`));
  } finally {
    globalThis.fetch = originalFetch;
  }
});
