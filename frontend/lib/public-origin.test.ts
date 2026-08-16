import assert from 'node:assert/strict';
import test from 'node:test';
import {
  requestOriginFromHeaders,
  resolvePublicOrigin,
  sanitizePublicUrl,
  sanitizePublicUrlJson,
} from './public-origin';

test('converts private absolute URLs to same-origin paths', () => {
  assert.equal(
    sanitizePublicUrl('https://192.168.11.22:8443/pages/owner/site/?v=1'),
    '/pages/owner/site/?v=1',
  );
  assert.equal(sanitizePublicUrl('http://forgejo:3000/user/avatar/a'), '/user/avatar/a');
  assert.equal(sanitizePublicUrl('https://[fc00::1]:8443/pages/site/'), '/pages/site/');
  assert.equal(sanitizePublicUrl('//forgejo:3000/private'), undefined);
});

test('keeps public absolute URLs and relative paths usable', () => {
  assert.equal(sanitizePublicUrl('https://pages.example/site/'), 'https://pages.example/site/');
  assert.equal(sanitizePublicUrl('/pages/owner/site/'), '/pages/owner/site/');
});

test('normalizes canonical private host forms before allowing absolute URLs', () => {
  assert.equal(sanitizePublicUrl('https://localhost./pages/site/'), '/pages/site/');
  assert.equal(sanitizePublicUrl('https://forgejo./api/v1'), '/api/v1');
  assert.equal(sanitizePublicUrl('https://[::ffff:192.168.1.22]:8443/pages/site/'), '/pages/site/');
  assert.equal(sanitizePublicUrl('https://[::ffff:c0a8:116]:8443/pages/site/'), '/pages/site/');
  assert.equal(sanitizePublicUrl('https:\\forgejo\\private'), undefined);
  assert.equal(sanitizePublicUrl('/\\\\evil.example/path'), undefined);
});

test('prefers a safe request origin when configuration points at a LAN host', () => {
  const requestHeaders = new Headers({
    host: 'madesk.tail8be30.ts.net',
    'x-forwarded-proto': 'https',
  });
  const requestOrigin = requestOriginFromHeaders(requestHeaders);
  assert.equal(requestOrigin, 'https://madesk.tail8be30.ts.net');
  assert.equal(
    resolvePublicOrigin('https://192.168.11.22:8443', requestOrigin),
    'https://madesk.tail8be30.ts.net',
  );
  assert.equal(resolvePublicOrigin('https://localhost:8443', undefined), undefined);
});

test('sanitizes Pages JSON responses before they reach browser HTML or scripts', () => {
  const sanitized = JSON.parse(sanitizePublicUrlJson(JSON.stringify({
    status: 'published',
    public_url: 'https://192.168.11.22:8443/pages/owner/site/',
    logs: [
      'Verified published URL https://192.168.11.22:8443/pages/owner/site/.',
      'See https://pages.example/owner/site/.',
      String.raw`escaped https:\\forgejo\private`,
    ],
    inspection: {
      public_url: 'https://forgejo:3000/pages/owner/site/',
      reasons: ['retry https://10.0.0.8:8000/status'],
    },
  })));
  assert.equal(sanitized.public_url, '/pages/owner/site/');
  assert.equal(sanitized.logs[0], 'Verified published URL /pages/owner/site/.');
  assert.equal(sanitized.logs[1], 'See https://pages.example/owner/site/.');
  assert.equal(sanitized.logs[2], 'escaped [internal URL omitted]');
  assert.equal(sanitized.inspection.public_url, '/pages/owner/site/');
  assert.equal(sanitized.inspection.reasons[0], 'retry /status');
});

test('fails closed when an upstream Pages response is not JSON', () => {
  assert.deepEqual(
    JSON.parse(sanitizePublicUrlJson('upstream https://192.168.11.22:8443/private')),
    { error: 'Upstream response was not valid JSON.' },
  );
});

test('request origin parsing rejects forwarded host path injection', () => {
  const headers = new Headers({
    'x-forwarded-host': 'madesk.tail8be30.ts.net/path',
    'x-forwarded-proto': 'https',
  });
  assert.equal(requestOriginFromHeaders(headers), undefined);
});
