import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  consumeNavigationRateLimit,
  classifyNavigationRoute,
  hasCommittedNavigationDestination,
  isSameNavigationDestination,
  isNavigationSample,
  navigationPathSearch,
  normalizeNavigationSample,
  pageHideOutcome,
  percentile,
  pruneExpiredNavigationRateLimits,
  summarizeNavigationSamples,
  shouldStartHistoryNavigation,
  usesClientNavigation,
  type NavigationSample,
} from './navigation-performance';

const pagesDeployWizardSource = readFileSync(
  new URL('../components/PagesDeployWizard.tsx', import.meta.url),
  'utf8',
);
const spaceEnvironmentSource = readFileSync(
  new URL('../components/SpaceEnvironmentButton.tsx', import.meta.url),
  'utf8',
);
const navigationFeedbackSource = readFileSync(
  new URL('../components/NavigationFeedback.tsx', import.meta.url),
  'utf8',
);
const searchFormSource = readFileSync(
  new URL('../components/SearchForm.tsx', import.meta.url),
  'utf8',
);

test('classifies navigation targets without retaining private URL data', () => {
  assert.equal(classifyNavigationRoute('/'), 'home');
  assert.equal(classifyNavigationRoute('/docs'), 'knowledge-list');
  assert.equal(classifyNavigationRoute('/docs/nyankoface/release-notes'), 'knowledge-detail');
  assert.equal(classifyNavigationRoute('/spaces'), 'catalog');
  assert.equal(classifyNavigationRoute('/nyankoface/sample-model'), 'repository-detail');
  assert.equal(classifyNavigationRoute('/pages/deploy'), 'pages-deploy');
  assert.equal(classifyNavigationRoute('/git/nyankoface/private'), 'forgejo');
});

test('keeps Next routes client-side and leaves gateway destinations as documents', () => {
  assert.equal(usesClientNavigation(classifyNavigationRoute('/nyankoface/sample-model')), true);
  assert.equal(usesClientNavigation(classifyNavigationRoute('/docs/nyankoface/release-notes')), true);
  assert.equal(usesClientNavigation(classifyNavigationRoute('/git/nyankoface/sample-model')), false);
  assert.equal(usesClientNavigation(classifyNavigationRoute('/run/nyankoface/sample-gradio/')), false);
});

test('ignores fragment-only history entries and measures path or query changes', () => {
  const previous = '/docs/nyankoface/release-notes?lang=ja';
  assert.equal(navigationPathSearch({ pathname: '/docs/nyankoface/release-notes', search: '?lang=ja' }), previous);
  assert.equal(shouldStartHistoryNavigation(previous, {
    pathname: '/docs/nyankoface/release-notes',
    search: '?lang=ja',
  }), false);
  assert.equal(shouldStartHistoryNavigation(previous, {
    pathname: '/docs/nyankoface/release-notes',
    search: '?lang=en',
  }), true);
  assert.equal(shouldStartHistoryNavigation(previous, { pathname: '/docs', search: '' }), true);
});

test('canonicalizes equivalent space encodings in navigation queries', () => {
  assert.equal(
    navigationPathSearch({ pathname: '/models', search: '?q=text%20generation&sort=updated' }),
    '/models?q=text+generation&sort=updated',
  );
  assert.equal(
    navigationPathSearch({ pathname: '/models', search: 'q=text+generation&sort=updated' }),
    '/models?q=text+generation&sort=updated',
  );
  assert.equal(
    isSameNavigationDestination(
      { pathname: '/models', search: '?q=text%20generation&sort=updated' },
      { pathname: '/models', search: '?q=text+generation&sort=updated' },
    ),
    true,
  );
  assert.equal(
    isSameNavigationDestination(
      { pathname: '/models', search: '?q=text+generation' },
      { pathname: '/models', search: '?q=image+generation' },
    ),
    false,
  );
});

test('uses canonical destinations before starting click, form, or programmatic feedback', () => {
  assert.equal(
    (navigationFeedbackSource.match(/isSameNavigationDestination\((?:target|resolvedTarget), current\)/g) ?? []).length,
    3,
  );
});

test('passes the saved pre-popstate location into history navigation tracking', () => {
  assert.match(
    navigationFeedbackSource,
    /if \(previousPathSearch === null\)[\s\S]*?begin\(window\.location\.href, null\)[\s\S]*?const sourceUrl = new URL\(previousPathSearch, window\.location\.origin\)[\s\S]*?begin\(window\.location\.href, null, false, \{[\s\S]*?pathname: sourceUrl\.pathname,/,
  );
  assert.match(
    navigationFeedbackSource,
    /sourcePathname: sourceLocation\?\.pathname \?\? window\.location\.pathname,/,
  );
});

test('cancels an abandoned navigation when history returns to its source', () => {
  assert.match(
    navigationFeedbackSource,
    /!shouldStartHistoryNavigation\(previousPathSearch, window\.location\)[\s\S]*?const active = activeRef\.current;[\s\S]*?const activeTarget = new URL\(active\.target, window\.location\.href\);[\s\S]*?activeTarget\.pathname\}\$\{activeTarget\.search\}` !== currentPathSearch[\s\S]*?finish\('cancelled'\);/,
  );
});

test('records only expected document unloads as successful', () => {
  assert.equal(pageHideOutcome(true), 'success');
  assert.equal(pageHideOutcome(false), 'cancelled');
});

test('finishes a committed query-only destination even when its markup is unchanged', () => {
  assert.equal(hasCommittedNavigationDestination({
    targetPathSearch: '/models?q=vision',
    currentPathSearch: '/models?q=audio',
  }), false);
  assert.equal(hasCommittedNavigationDestination({
    targetPathSearch: '/models?q=vision',
    currentPathSearch: '/models?q=vision',
  }), true);
});

test('preserves document navigation for gateway-owned forms and searches', () => {
  assert.match(
    navigationFeedbackSource,
    /const clientNavigation = usesClientNavigation\(classifyNavigationRoute\(target\.pathname\)\);[\s\S]*?begin\(target\.href, null, !clientNavigation\)[\s\S]*?if \(!clientNavigation\) return;[\s\S]*?event\.preventDefault\(\);/,
  );
  assert.match(
    navigationFeedbackSource,
    /const retry = \(\) => \{[\s\S]*?const clientNavigation = usesClientNavigation\(route\);[\s\S]*?begin\(target, null, !clientNavigation\)[\s\S]*?else window\.location\.assign\(target\);/,
  );
  assert.match(searchFormSource, /if \(clientNavigation\) router\.push\(href\);\s*else window\.location\.assign\(href\);/);
});

test('client-managed mutation forms opt out of global GET navigation capture', () => {
  assert.match(pagesDeployWizardSource, /<form[\s\S]*?onSubmit=\{deploy\}[\s\S]*?data-navigation-feedback="off"/);
  assert.match(spaceEnvironmentSource, /<form[\s\S]*?onSubmit=\{save\}[\s\S]*?data-navigation-feedback="off"/);
});

test('calculates nearest-rank percentiles and successful navigation summaries', () => {
  assert.equal(percentile([100, 250, 300, 900], 0.5), 250);
  assert.equal(percentile([100, 250, 300, 900], 0.95), 900);

  const samples: NavigationSample[] = [
    { route: 'catalog', durationMs: 120, feedbackMs: 14, outcome: 'success', viewport: 'desktop', cache: 'cold' },
    { route: 'catalog', durationMs: 240, feedbackMs: 21, outcome: 'success', viewport: 'mobile', cache: 'warm' },
    { route: 'catalog', durationMs: 15_000, feedbackMs: 18, outcome: 'timeout', viewport: 'mobile', cache: 'warm' },
  ];

  assert.deepEqual(summarizeNavigationSamples('catalog', samples), {
    route: 'catalog',
    count: 3,
    successful: 2,
    p50Ms: 120,
    p95Ms: 240,
    feedbackP95Ms: 21,
  });
});

test('rejects malformed or unbounded telemetry samples', () => {
  assert.equal(isNavigationSample({
    route: 'home', durationMs: 200, feedbackMs: 20, outcome: 'success', viewport: 'desktop', cache: 'warm',
  }), true);
  assert.equal(isNavigationSample({
    route: '/private/path', durationMs: 200, feedbackMs: 20, outcome: 'success', viewport: 'desktop', cache: 'warm',
  }), false);
  assert.equal(isNavigationSample({
    route: 'home', durationMs: 60_001, feedbackMs: 20, outcome: 'success', viewport: 'desktop', cache: 'warm',
  }), false);
});

test('normalizes telemetry without retaining unknown or private properties', () => {
  const normalized = normalizeNavigationSample({
    route: 'catalog',
    durationMs: 200,
    feedbackMs: 20,
    outcome: 'success',
    viewport: 'desktop',
    cache: 'warm',
    path: '/private/repository',
    userId: 'should-not-be-retained',
  });
  assert.deepEqual(normalized, {
    route: 'catalog',
    durationMs: 200,
    feedbackMs: 20,
    outcome: 'success',
    viewport: 'desktop',
    cache: 'warm',
  });
});

test('rate limits one navigation telemetry client within a fixed window', () => {
  let bucket;
  for (let index = 0; index < 30; index += 1) {
    const result = consumeNavigationRateLimit(bucket, 1_000);
    assert.equal(result.allowed, true);
    bucket = result.bucket;
  }
  assert.equal(consumeNavigationRateLimit(bucket, 1_001).allowed, false);
  assert.equal(consumeNavigationRateLimit(bucket, 61_000).allowed, true);
});

test('prunes expired navigation telemetry clients without removing active buckets', () => {
  const buckets = new Map([
    ['expired', { startedAt: 1_000, count: 4 }],
    ['active', { startedAt: 60_000, count: 2 }],
  ]);
  assert.equal(pruneExpiredNavigationRateLimits(buckets, 61_000), 1);
  assert.deepEqual([...buckets.keys()], ['active']);
});
