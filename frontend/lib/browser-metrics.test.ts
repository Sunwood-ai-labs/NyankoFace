import assert from 'node:assert/strict';
import test from 'node:test';
import { browserViewIdempotencyKey, ensureBrowserView } from './browser-metrics';

test('shares one page-load view write between concurrent consumers', async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = (globalThis as typeof globalThis & { window?: typeof globalThis }).window;
  let calls = 0;

  Object.defineProperty(globalThis, 'window', { configurable: true, value: globalThis });
  globalThis.fetch = async (_input, init) => {
    calls += 1;
    assert.equal(init?.method, 'POST');
    assert.equal((init?.headers as Record<string, string>)['Idempotency-Key'], browserViewIdempotencyKey('test-owner', 'test-repo'));
    return new Response(JSON.stringify({ metrics: { views: 7, likes: 2 } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  try {
    const [first, second] = await Promise.all([
      ensureBrowserView('test-owner', 'test-repo'),
      ensureBrowserView('test-owner', 'test-repo'),
    ]);
    assert.equal(calls, 1);
    assert.deepEqual(first, { views: 7, likes: 2 });
    assert.deepEqual(second, first);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, 'window');
    } else {
      Object.defineProperty(globalThis, 'window', { configurable: true, value: originalWindow });
    }
  }
});
