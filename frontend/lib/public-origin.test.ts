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
  })));
  assert.equal(sanitized.public_url, '/pages/owner/site/');
});

test('request origin parsing rejects forwarded host path injection', () => {
  const headers = new Headers({
    'x-forwarded-host': 'madesk.tail8be30.ts.net/path',
    'x-forwarded-proto': 'https',
  });
  assert.equal(requestOriginFromHeaders(headers), undefined);
});
