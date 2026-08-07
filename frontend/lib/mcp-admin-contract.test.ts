import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

import {
  adminSubject,
  ADMIN_MAX_BODY_BYTES,
  ADMIN_BFF_TIMEOUT_MS,
  boundedForgejoFetch,
  boundedForgejoFetchAndRead,
  issueReauthProof,
  isSecureAdminTransport,
  remainingDeadline,
  readBoundedRequestBody,
  safeAdminRoute,
  sanitizeAdminPayload,
  verifyReauthProof,
} from './mcp-admin-contract';
import { preserveOneTimeResult } from '../components/McpAdminConsole';
import {
  isActiveToken,
  isValidServiceAccountId,
  tokenLifetimeSeconds,
} from './mcp-admin-ui';

test('Forgejo fetch deadline aborts a stalled transport and fails closed', async () => {
  let observedSignal: AbortSignal | undefined;
  const stalledFetch = ((_input: string | URL | Request, init?: RequestInit) => {
    observedSignal = init?.signal || undefined;
    return new Promise<Response>((_resolve, reject) => {
      observedSignal?.addEventListener('abort', () => reject(new Error('sensitive detail')));
    });
  }) as typeof fetch;

  const response = await boundedForgejoFetch(stalledFetch, 'http://forgejo/user/settings', {}, 10);
  assert.equal(response, null);
  assert.equal(observedSignal?.aborted, true);
});

test('Forgejo fetch deadline remains active while consuming the response body', async () => {
  let observedSignal: AbortSignal | undefined;
  const stalledBodyFetch = ((_input: string | URL | Request, init?: RequestInit) => {
    observedSignal = init?.signal || undefined;
    return Promise.resolve(new Response(new ReadableStream({
      start(controller) {
        observedSignal?.addEventListener('abort', () => controller.error(new Error('stalled body')));
      },
    })));
  }) as typeof fetch;

  const result = await boundedForgejoFetchAndRead(
    stalledBodyFetch,
    'http://forgejo/user/settings',
    {},
    (response) => response.text(),
    10,
  );
  assert.equal(result, null);
  assert.equal(observedSignal?.aborted, true);
});

test('Forgejo and admin calls consume one overall BFF deadline', () => {
  const startedAt = 1_800_000_000_000;
  const deadline = startedAt + ADMIN_BFF_TIMEOUT_MS;
  assert.equal(remainingDeadline(deadline, startedAt), 35_000);
  assert.equal(remainingDeadline(deadline, startedAt + 10_000), 25_000);
  assert.equal(remainingDeadline(deadline, deadline + 1), 0);
  const source = readFileSync(new URL('./mcp-admin.ts', import.meta.url), 'utf8');
  const forgejoSource = readFileSync(new URL('./forgejo-session.ts', import.meta.url), 'utf8');
  assert.match(source, /forgejoBrowserSession\(forgejoCookie, remainingDeadline\(deadline\), \{ failClosed: true \}\)/);
  assert.match(source, /verifyForgejoPassword\(session\.username!, password, otp, remainingDeadline\(deadline\)\)/);
  assert.match(source, /AbortSignal\.timeout\(remainingDeadline\(deadline\)\)/);
  assert.equal((forgejoSource.match(/timeoutMs\);/g) || []).length, 2);
  assert.match(forgejoSource, /X-Forgejo-OTP/);
});

test('admin request bodies are bounded by bytes and an absolute deadline', async () => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('{"safe":true}'));
      controller.close();
    },
  });
  assert.deepEqual(await readBoundedRequestBody(body, 100), {
    body: '{"safe":true}', bytes: 13,
  });
  const oversized = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(ADMIN_MAX_BODY_BYTES + 1));
      controller.close();
    },
  });
  assert.deepEqual(await readBoundedRequestBody(oversized, 100), { error: 'too_large' });
  const stalled = new ReadableStream<Uint8Array>({ start() {} });
  assert.deepEqual(await readBoundedRequestBody(stalled, 10), { error: 'timeout' });
});

test('one-time result is revealed even when the following refresh fails', async () => {
  const token = { token: 'one-time-secret', token_id: 'token-1' };
  const events: string[] = [];
  const result = await preserveOneTimeResult(
    token,
    (value) => events.push(`revealed:${value.token_id}`),
    async () => { events.push('refresh'); throw new Error('transient refresh failure'); },
  );
  assert.equal(result, token);
  assert.deepEqual(events, ['revealed:token-1', 'refresh']);
});

test('admin subject fails closed for anonymous members and missing usernames', () => {
  assert.equal(adminSubject({ authenticated: false }), null);
  assert.equal(adminSubject({ authenticated: true, username: 'member' }), null);
  assert.equal(adminSubject({ authenticated: true, isAdmin: true }), null);
  assert.equal(adminSubject({ authenticated: true, isAdmin: true, username: 'root' }), 'human:root');
});

test('admin proxy only permits bounded API routes', () => {
  assert.equal(safeAdminRoute(['reauth']), 'reauth');
  assert.equal(safeAdminRoute(['state']), 'state');
  assert.equal(safeAdminRoute(['tokens', 'abc-123', 'rotate']), 'tokens/abc-123/rotate');
  assert.equal(
    safeAdminRoute(['service-accounts', 'service:codex', 'disable']),
    'service-accounts/service:codex/disable',
  );
  assert.equal(safeAdminRoute(['../../health']), null);
  assert.equal(safeAdminRoute(['tokens', 'abc', 'delete']), null);
  assert.equal(safeAdminRoute(['service-accounts', 'service:codex', 'delete']), null);
  assert.equal(safeAdminRoute(['service-accounts', 'service/account', 'disable']), null);
});

test('service-account creation matches action routes and rotation preserves lifetime', () => {
  assert.equal(isValidServiceAccountId('service:codex'), true);
  assert.equal(isValidServiceAccountId('service account'), false);
  assert.equal(isValidServiceAccountId('service/account'), false);
  assert.equal(isValidServiceAccountId('.'), false);
  assert.equal(isValidServiceAccountId('..'), false);
  assert.equal(isValidServiceAccountId(`service:${'x'.repeat(128)}`), false);
  assert.equal(tokenLifetimeSeconds({ created_at: 1_000, expires_at: 1_600 }), 600);
  assert.equal(tokenLifetimeSeconds({ created_at: 1_600, expires_at: 1_000 }), 60);
  assert.equal(tokenLifetimeSeconds({ created_at: 1_000, expires_at: 99_999_999 }), 7_776_000);
  assert.equal(isActiveToken({ expires_at: 2_000, revoked_at: null }, 1_000), true);
  assert.equal(isActiveToken({ expires_at: 1_000, revoked_at: null }, 1_000), false);
  assert.equal(isActiveToken({ expires_at: 2_000, revoked_at: 1_500 }, 1_000), false);
  const source = readFileSync(new URL('../components/McpAdminConsole.tsx', import.meta.url), 'utf8');
  assert.match(source, /ttl_seconds: tokenLifetimeSeconds\(token\)/);
  assert.match(source, /const form = event\.currentTarget; const data = new FormData\(form\)/);
  assert.match(source, /isActiveToken\(item, now\)/);
  assert.match(source, /setInterval\(\(\) => setNow\(Math\.floor\(Date\.now\(\) \/ 1000\)\), 1000\)/);
  assert.match(source, /tokenActionLock/);
  assert.match(source, /tokenActionsDisabled = Boolean\(busy\) \|\| secret !== null/);
  assert.match(source, /accountMutationsDisabled = Boolean\(busy\) \|\| secret !== null/);
  assert.match(source, /disabled=\{accountMutationsDisabled\}/);
  assert.match(source, /if \(!result\?\.token\) tokenActionLock\.current = false/);
  assert.match(source, /releaseTokenAction\(\)/);
  assert.match(source, /disabled=\{Boolean\(busy\)\}/);
  assert.doesNotMatch(source, /ttl_seconds:\s*2592000/);
});

test('admin control plane requires HTTPS at the app and gateway edges', () => {
  assert.equal(isSecureAdminTransport(new Headers({ 'x-forwarded-proto': 'https' })), true);
  assert.equal(isSecureAdminTransport(new Headers({ 'x-forwarded-proto': 'http' })), false);
  assert.equal(isSecureAdminTransport(new Headers()), false);
  assert.equal(isSecureAdminTransport(new Headers(), 'https://nyankoface.example/admin/mcp'), true);
  const page = readFileSync(new URL('../app/admin/mcp/page.tsx', import.meta.url), 'utf8');
  assert.match(page, /isSecureAdminTransport\(requestHeaders\)/);
  const gateway = readFileSync(new URL('../../gateway/nginx.conf', import.meta.url), 'utf8');
  assert.match(gateway, /location \^~ \/api\/admin\/mcp\//);
  assert.match(gateway, /location \^~ \/admin\/mcp\//);
});

test('fresh reauthentication proof is bound to session and subject', () => {
  const now = 1_800_000_000;
  const secret = 'internal-secret-that-is-long-enough';
  const proof = issueReauthProof('human:admin', 'session-a', secret, now);
  assert.equal(verifyReauthProof(proof, 'human:admin', 'session-a', secret, now + 300), now);
  assert.equal(verifyReauthProof(null, 'human:admin', 'session-a', secret, now), null);
  assert.equal(verifyReauthProof(`${proof}x`, 'human:admin', 'session-a', secret, now), null);
  assert.equal(verifyReauthProof(proof, 'human:other', 'session-a', secret, now), null);
  assert.equal(verifyReauthProof(proof, 'human:admin', 'session-b', secret, now), null);
  assert.equal(verifyReauthProof(proof, 'human:admin', 'session-a', secret, now + 301), null);
  assert.equal(verifyReauthProof(proof, 'human:admin', 'session-a', secret, now - 1), null);
});

test('admin BFF verifies credentials and forwards only a verified proof time', () => {
  const source = readFileSync(new URL('./mcp-admin.ts', import.meta.url), 'utf8');
  assert.match(source, /const forgejoCookie = forgejoSessionId/);
  assert.match(source, /forgejoBrowserSession\(forgejoCookie, remainingDeadline\(deadline\), \{ failClosed: true \}\)/);
  assert.doesNotMatch(source, /forgejoBrowserSession\(cookieHeader/);
  assert.match(source, /verifyForgejoPassword\(session\.username!, password, otp, remainingDeadline\(deadline\)\)/);
  assert.match(source, /HttpOnly; Secure; SameSite=Strict/);
  assert.match(source, /verifyReauthProof\(/);
  assert.match(source, /'X-NyankoFace-Admin-Reauthenticated-At': String\(reauthenticatedAt\)/);
  assert.doesNotMatch(source, /'X-NyankoFace-Admin-Reauthenticated-At': String\(Math\.floor/);
});

test('admin payload strips backend-only secrets and allows plaintext once', () => {
  const value = { token: 'plain', token_sha256: 'digest', nested: {
    forgejo_token_file: '/secret/path', event_hash: 'hash', safe: true,
  } };
  assert.deepEqual(sanitizeAdminPayload(value), { nested: { safe: true } });
  assert.deepEqual(sanitizeAdminPayload(value, true), { token: 'plain', nested: { safe: true } });
});

test('client examples use secret placeholders rather than embedded credentials', () => {
  const source = readFileSync(new URL('../components/McpAdminConsole.tsx', import.meta.url), 'utf8');
  assert.match(source, /title="Claude Desktop"/);
  assert.match(source, /NYANKOFACE_MCP_TOKEN_FILE/);
  assert.match(source, /<TOKEN_FILE>/);
  assert.match(source, /\$\{input:nyankoface-token\}/);
  assert.match(source, /"inputs": \[/);
  assert.match(source, /"password": true/);
  assert.doesNotMatch(source, /Bearer\s+(?:sk-|ofm_)[a-zA-Z0-9_-]+/);
});

test('policy, audit, and connection controls match backend contracts', () => {
  const source = readFileSync(new URL('../components/McpAdminConsole.tsx', import.meta.url), 'utf8');
  assert.match(source, /value="service_account"/);
  assert.doesNotMatch(source, /value="client"/);
  for (const outcome of ['allowed', 'denied', 'failed', 'replayed', 'changed']) {
    assert.match(source, new RegExp(`<option>${outcome}</option>`));
  }
  assert.match(source, /type="datetime-local" name="after"/);
  assert.match(source, /type="datetime-local" name="before"/);
  assert.match(source, /function ConnectionStatus/);
  assert.match(source, /report\.reason_code/);
});

test('one-time token is destroyed after copy, close, and browser lifecycle events', () => {
  const source = readFileSync(new URL('../components/McpAdminConsole.tsx', import.meta.url), 'utf8');
  assert.match(source, /addEventListener\('pagehide', destroy\)/);
  assert.match(source, /addEventListener\('beforeunload', destroy\)/);
  assert.match(source, /clipboard\.writeText\(secret\.token\);\s*releaseTokenAction\(\)/);
  assert.doesNotMatch(
    source,
    /(?:localStorage|sessionStorage|history|console)\.[a-zA-Z]+\([^)]*secret\.token/,
  );
  assert.match(source, /<form method="post" onSubmit=\{reauthenticate\}/);
  assert.match(source, /name="password"[^>]*autoComplete="current-password"/);
  assert.match(source, /finally \{ password = ''; otp = ''; form\.reset\(\);/);
  assert.match(source, /name="otp"/);
  assert.match(source, /one-time-code/);
});
