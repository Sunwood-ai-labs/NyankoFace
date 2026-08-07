import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { navigationBrandAuditRoutes, viewports } from './routes.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const sourceRoot = resolve(root);
const baseUrl = (process.env.NAVIGATION_BRAND_BASE_URL || process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const docsBaseUrl = (process.env.NAVIGATION_BRAND_DOCS_BASE_URL || '').replace(/\/$/, '');
const localOrigin = new URL(baseUrl).origin;
const outputDir = resolve(process.env.NAVIGATION_BRAND_OUTPUT_DIR || join(root, 'visual-tests', 'artifacts', 'navigation-brand'));
const sourceOnly = process.env.NAVIGATION_BRAND_SOURCE_ONLY === '1';
const timeoutMs = Number(process.env.NAVIGATION_BRAND_TIMEOUT_MS || 20_000);

const sourcePaths = {
  navigation: 'frontend/public/nyankoface-navigation.json',
  navbar: 'frontend/components/Navbar.tsx',
  layout: 'frontend/app/layout.tsx',
  forgejoHeader: 'forgejo/custom/templates/custom/header.tmpl',
  forgejoDockerfile: 'forgejo/Dockerfile',
  docsConfig: 'docs/.vitepress/config.mts',
};

const readSource = async (relativePath) => readFile(join(sourceRoot, relativePath), 'utf8');
const source = Object.fromEntries(await Promise.all(
  Object.entries(sourcePaths).map(async ([key, relativePath]) => [key, await readSource(relativePath)]),
));
const navigation = JSON.parse(source.navigation);

const check = (name, passed, detail = {}) => ({ name, passed: Boolean(passed), detail });
const normalizeHref = (href) => {
  try {
    const url = new URL(href, 'https://nyankoface.invalid');
    const pathname = url.pathname.replace(/\/{2,}/g, '/').replace(/\/$/, '') || '/';
    const origin = url.origin === 'https://nyankoface.invalid' || url.origin === localOrigin ? '' : url.origin;
    return `${origin}${pathname}${url.search}`;
  } catch {
    return String(href || '').trim();
  }
};

const canonicalBrandRequirements = {
  portal: { all: ['/brand/favicon.svg'], any: [], visibleAll: ['/brand/nyankoface-paw-logo.png'], visibleAny: [] },
  forgejo: { all: ['/img/favicon.svg'], any: [], visibleAll: [], visibleAny: ['/img/logo.png', '/brand/nyankoface-paw-logo.png'] },
  docs: { all: ['/pwa-192x192.png'], any: [], visibleAll: ['/pwa-512x512.png'], visibleAny: [] },
};

function publishItemsForState(authState) {
  return (navigation.publish || []).filter((item) => {
    if (item.auth === 'admin') return authState === 'admin';
    if (item.auth === 'authenticated') return authState === 'authenticated' || authState === 'admin';
    return true;
  });
}

function canonicalItemsForState(authState) {
  return [
    ...(navigation.primary || []),
    ...(navigation.explore || []),
    ...(navigation.community || []),
    ...publishItemsForState(authState),
  ];
}

function expectedHrefsForState(authState) {
  return new Set(canonicalItemsForState(authState).map((item) => normalizeHref(item.href)));
}

function expectedNavigationForState(authState) {
  return canonicalItemsForState(authState).map((item) => ({
    href: normalizeHref(item.href),
    labels: [item.label, item.labelJa].filter(Boolean),
  }));
}

async function sourceAudit() {
  const checks = [];
  const allItems = [
    ...(navigation.primary || []),
    ...(navigation.explore || []),
    ...(navigation.community || []),
    ...(navigation.publish || []),
  ];
  const ids = allItems.map((item) => item.id);
  const hrefs = allItems.map((item) => item.href);
  checks.push(check('navigation manifest has one versioned source of truth',
    Number.isInteger(navigation.version) && navigation.version > 0
      && navigation.brand?.markSrc === '/brand/nyankoface-paw-logo.png'
      && new Set(ids).size === ids.length
      && hrefs.every((href) => typeof href === 'string' && href.length > 0),
    { version: navigation.version, itemCount: allItems.length, duplicateIds: ids.filter((id, index) => ids.indexOf(id) !== index) }));
  checks.push(check('portal consumes every navigation group and canonical brand mark',
    ['nyankoFaceNavigation.primary', 'nyankoFaceNavigation.explore', 'nyankoFaceNavigation.community', 'nyankoFaceNavigation.publish', 'BrandMark'].every((token) => source.navbar.includes(token)),
    { file: sourcePaths.navbar }));
  checks.push(check('portal layout exposes the versioned metadata and navigation shell',
    source.layout.includes('BRAND_VERSION') && source.layout.includes('/brand/favicon.svg') && source.layout.includes('<Navbar appName={appName}'),
    { file: sourcePaths.layout }));
  checks.push(check('Forgejo consumes the shared navigation manifest with progressive fallback',
    source.forgejoHeader.includes('fetch("/nyankoface-navigation.json"')
      && source.forgejoHeader.includes('syncCanonicalNavigation')
      && source.forgejoHeader.includes('nyankoface-canonical-primary')
      && source.forgejoHeader.includes('nyankoface-mobile-menu-sheet')
      && source.forgejoHeader.includes('config.primary')
      && source.forgejoHeader.includes('config.brand.markSrc'),
    { file: sourcePaths.forgejoHeader }));
  checks.push(check('Forgejo image wiring points to generated canonical assets',
    source.forgejoDockerfile.includes('public/brand/nyankoface-paw-logo.png')
      && source.forgejoDockerfile.includes('/custom/public/assets/img/logo.png')
      && source.forgejoDockerfile.includes('public/brand/favicon.svg'),
    { file: sourcePaths.forgejoDockerfile }));
  checks.push(check('VitePress uses the shared brand asset family',
    source.docsConfig.includes("logo: '/pwa-512x512.png'")
      && source.docsConfig.includes("apple-touch-icon.png")
      && source.docsConfig.includes("mask-icon.svg")
      && source.docsConfig.includes("manifest.webmanifest"),
    { file: sourcePaths.docsConfig }));

  const stalePatterns = [
    { id: 'legacy Forgejo logo.svg reference', pattern: /(?:AssetUrlPrefix|\/assets\/img)\/logo\.svg/i },
    { id: 'legacy NyankoFace mark-v2 reference', pattern: /nyankoface-mark-v2\.png/i },
    { id: 'legacy text-only OF logo reference', pattern: /(?:textContent|innerHTML)\s*=\s*['"`]OF['"`]/i },
  ];
  const staleReferences = stalePatterns.flatMap(({ id, pattern }) => Object.entries(source)
    .filter(([, contents]) => pattern.test(contents))
    .map(([file]) => ({ id, file: sourcePaths[file] })));
  checks.push(check('legacy platform brand references are absent from active source', staleReferences.length === 0, { staleReferences }));
  checks.push(check('legacy assets are inventory-only and not silently used',
    !source.forgejoHeader.includes('/img/logo.svg') && !source.navbar.includes('nyankoface-mark-v2.png'),
    { inventoryOnly: ['forgejo/custom/public/assets/img/logo.svg', 'forgejo/custom/public/assets/img/nyankoface-mark-v2.png'] }));

  return { passed: checks.every((item) => item.passed), checks };
}

function authStateSpecs() {
  const specs = [{ id: 'anonymous' }];
  for (const id of ['authenticated', 'admin']) {
    const path = process.env[`NAVIGATION_BRAND_${id.toUpperCase()}_STATE`];
    if (path) specs.push({ id, storageState: resolve(path) });
  }
  return specs;
}

function baseForRoute(route) {
  return route.target === 'docs' ? docsBaseUrl : baseUrl;
}

async function clickDisclosure(page, selector) {
  const target = page.locator(selector).first();
  if (await target.count() === 0) return false;
  await target.click({ force: true });
  return true;
}

async function waitForCanonicalNavigation(page, target, viewportId) {
  if (target !== 'forgejo') return;
  await page.waitForFunction(({ mobile }) => {
    const version = document.body?.getAttribute('data-nyankoface-navigation-version');
    const navigation = mobile
      ? document.querySelector('.nyankoface-mobile-menu-sheet > section:nth-child(2) a[href]')
      : document.querySelector('.nyankoface-canonical-primary');
    return Boolean(version && navigation);
  }, { mobile: viewportId === 'mobile' }, { timeout: timeoutMs });
}

async function inspectPage(page, target, authState, viewportId, expectedNavigation) {
  await waitForCanonicalNavigation(page, target, viewportId);
  if (target === 'portal') {
    if (viewportId === 'desktop') await clickDisclosure(page, '.nyankoface-global-explore > summary');
    if (viewportId === 'mobile') await clickDisclosure(page, '.nyankoface-mobile-menu-toggle');
  }
  if (target === 'forgejo') {
    if (viewportId === 'desktop') await clickDisclosure(page, '.nyankoface-forgejo-more > summary');
    if (viewportId === 'mobile') await clickDisclosure(page, '#navbar-expand-toggle');
  }
  return page.evaluate(({ target: shellTarget, auth, expectedBrandRequirements, expectedNavigation: expectedItems }) => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      return !element.hasAttribute('hidden')
        && element.getAttribute('aria-hidden') !== 'true'
        && style.display !== 'none'
        && style.visibility !== 'hidden'
        && element.getClientRects().length > 0;
    };
    const href = (element) => element.href || element.getAttribute('href') || '';
    const linkData = (root) => Array.from(root?.querySelectorAll('a[href]') || [])
      .filter(visible)
      .map((element) => ({ href: href(element), text: element.textContent?.replace(/\s+/g, ' ').trim() || '' }));
    const normalizeLink = (value) => {
      try {
        const url = new URL(value, window.location.href);
        const pathname = url.pathname.replace(/\/{2,}/g, '/').replace(/\/$/, '') || '/';
        const origin = url.origin === window.location.origin ? '' : url.origin;
        return `${origin}${pathname}${url.search}`;
      } catch {
        return String(value || '').trim();
      }
    };
    const shell = shellTarget === 'portal'
      ? (document.querySelector('.nyankoface-global-header') ? 'portal' : null)
      : shellTarget === 'forgejo'
        ? (document.querySelector('#navbar') ? 'forgejo' : null)
        : (document.querySelector('.VPNav') ? 'docs' : null);
    const shellRoot = shellTarget === 'portal'
      ? document.querySelector('.nyankoface-global-header')
      : shellTarget === 'forgejo'
        ? document.querySelector('#navbar')
        : document.querySelector('.VPNav');
    let roots = [];
    if (shellTarget === 'portal') {
      roots = [document.querySelector(window.innerWidth <= 600 ? '.nyankoface-mobile-panel nav' : '.nyankoface-global-header nav')].filter(Boolean);
    } else if (shellTarget === 'forgejo') {
      roots = window.innerWidth <= 600
        ? Array.from(document.querySelectorAll('.nyankoface-mobile-menu-sheet > section')).slice(1)
        : [document.querySelector('.nyankoface-canonical-primary')].filter(Boolean);
    } else {
      roots = [document.querySelector('.VPNav')].filter(Boolean);
    }
    const links = roots.flatMap(linkData);
    const profileMenu = shellTarget === 'forgejo'
      ? document.querySelector('#navbar .navbar-right .ui.dropdown[aria-label="Profile and settings…"] .menu')
      : null;
    const sessionProfileHref = Array.from(profileMenu?.querySelectorAll('a[href]') || [])
      .find((link) => {
        const value = link.getAttribute('href') || '';
        return value && !/\/user\/(?:settings|logout)|\/notifications|\/admin(?:\/|$)|forgejo\.org\/docs|[?&]tab=stars(?:&|$)/.test(value);
      })?.href || '';
    const accountHrefs = [
      '/git/user/login',
      '/git/user/sign_up',
      '/git/user/settings',
      '/git/user/logout',
      sessionProfileHref,
    ].filter(Boolean).map((value) => normalizeLink(value).split('?')[0]);
    const brandRefs = Array.from(document.querySelectorAll('img[src], link[href], meta[content]'))
      .map((element) => element.getAttribute('src') || element.getAttribute('href') || element.getAttribute('content') || '')
      .filter(Boolean);
    const visibleImageRefs = Array.from(shellRoot?.querySelectorAll('img[src]') || [])
      .filter(visible)
      .map((element) => element.getAttribute('src') || '')
      .filter(Boolean);
    const linkRefs = Array.from(document.querySelectorAll('link[href]'))
      .map((element) => element.getAttribute('href') || '')
      .filter(Boolean);
    const staleRefs = brandRefs.filter((value) => /(?:\/img\/logo\.svg|nyankoface-mark-v2|["']OF["'])/i.test(value));
    const missingCanonicalRefs = expectedBrandRequirements.all
      .filter((token) => !linkRefs.some((value) => value.includes(token)))
      .concat(expectedBrandRequirements.visibleAll
        .filter((token) => !visibleImageRefs.some((value) => value.includes(token))));
    if (expectedBrandRequirements.any.length > 0
      && !expectedBrandRequirements.any.some((token) => linkRefs.some((value) => value.includes(token)))) {
      missingCanonicalRefs.push(`one of: ${expectedBrandRequirements.any.join(', ')}`);
    }
    if (expectedBrandRequirements.visibleAny.length > 0
      && !expectedBrandRequirements.visibleAny.some((token) => visibleImageRefs.some((value) => value.includes(token)))) {
      missingCanonicalRefs.push(`one visible image of: ${expectedBrandRequirements.visibleAny.join(', ')}`);
    }
    const hrefCounts = links.reduce((counts, item) => counts.set(item.href, (counts.get(item.href) || 0) + 1), new Map());
    const duplicateHrefs = Array.from(hrefCounts.entries()).filter(([, count]) => count > 1).map(([value, count]) => ({ value, count }));
    const expectedByHref = new Map(expectedItems.map((item) => [item.href, item.labels]));
    const expectedOrder = expectedItems.map((item) => item.href);
    const actualOrder = links.map((item) => normalizeLink(item.href)).filter((href) => expectedByHref.has(href));
    const orderMismatches = Array.from({ length: Math.max(expectedOrder.length, actualOrder.length) }, (_, index) => ({
      index,
      expected: expectedOrder[index] || null,
      actual: actualOrder[index] || null,
    })).filter((item) => item.expected !== item.actual);
    const labelMismatches = links.flatMap((item) => {
      const expectedLabels = expectedByHref.get(normalizeLink(item.href));
      if (!expectedLabels || expectedLabels.includes(item.text)) return [];
      return [{ href: normalizeLink(item.href), actual: item.text, expected: expectedLabels }];
    });
    return {
      shell,
      auth,
      links,
      brandRefs,
      staleRefs,
      expectedBrandRequirements,
      missingCanonicalRefs,
      duplicateHrefs,
      accountHrefs,
      expectedOrder,
      actualOrder,
      orderMismatches,
      labelMismatches,
      horizontalOverflow: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0) - document.documentElement.clientWidth,
      title: document.title,
    };
  }, {
    target,
    auth: authState,
    expectedBrandRequirements: canonicalBrandRequirements[target] || { all: [], any: [] },
    expectedNavigation,
  });
}

async function runtimeAudit() {
  if (sourceOnly) return { skipped: true, reason: 'NAVIGATION_BRAND_SOURCE_ONLY=1' };
  const docsRoutes = docsBaseUrl ? navigationBrandAuditRoutes.filter((route) => route.target === 'docs') : [];
  const routes = navigationBrandAuditRoutes.filter((route) => route.target !== 'docs' || docsBaseUrl);
  const skipped = navigationBrandAuditRoutes.filter((route) => route.target === 'docs' && !docsBaseUrl).map((route) => route.id);
  const results = [];
  const browser = await chromium.launch({ headless: true });
  try {
    for (const auth of authStateSpecs()) {
      for (const viewport of viewports) {
        const context = await browser.newContext({
          ignoreHTTPSErrors: true,
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: viewport.id === 'mobile' ? 'light' : 'dark',
          ...(auth.storageState ? { storageState: auth.storageState } : {}),
        });
        const page = await context.newPage();
        page.setDefaultTimeout(timeoutMs);
        page.setDefaultNavigationTimeout(timeoutMs);
        const consoleErrors = [];
        const pageErrors = [];
        const requestFailures = [];
        const httpErrors = [];
        page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
        page.on('pageerror', (error) => pageErrors.push(error.message));
        page.on('requestfailed', (request) => requestFailures.push(`${request.method()} ${request.url()} — ${request.failure()?.errorText || 'failed'}`));
        page.on('response', (response) => {
          if (response.status() >= 400) {
            httpErrors.push({
              status: response.status(),
              url: response.url(),
              resourceType: response.request().resourceType(),
            });
          }
        });
        for (const route of routes) {
          const routeBase = baseForRoute(route);
          const result = { route: route.id, target: route.target, auth: auth.id, viewport: viewport.id, url: routeBase ? `${routeBase}${route.path}` : null };
          const errorsBefore = {
            console: consoleErrors.length,
            page: pageErrors.length,
            request: requestFailures.length,
            http: httpErrors.length,
          };
          try {
            if (!routeBase) throw new Error(`No base URL configured for ${route.target}`);
            const response = await page.goto(`${routeBase}${route.path}`, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
            const status = response?.status() ?? null;
            const expectedNavigation = route.target === 'docs' ? [] : expectedNavigationForState(auth.id);
            const inspected = await inspectPage(page, route.target, auth.id, viewport.id, expectedNavigation);
            const expected = expectedHrefsForState(auth.id);
            const actual = inspected.links.map((item) => normalizeHref(item.href));
            const actualSet = new Set(actual);
            const missing = route.target === 'docs' ? [] : Array.from(expected).filter((href) => !actualSet.has(href));
            const accountHrefs = new Set(inspected.accountHrefs || []);
            const isAccountHref = (href) => accountHrefs.has(normalizeHref(href).split('?')[0]);
            const unexpected = route.target === 'docs' ? [] : Array.from(actualSet).filter((href) => !expected.has(href) && !(route.target === 'forgejo' && isAccountHref(href)));
            result.status = status;
            result.expectedStatuses = route.expectedStatuses;
            result.passed = route.expectedStatuses.includes(status)
              && inspected.shell === route.target
              && inspected.staleRefs.length === 0
              && inspected.missingCanonicalRefs.length === 0
              && (route.target === 'docs' || inspected.orderMismatches.length === 0)
              && (route.target === 'docs' || inspected.labelMismatches.length === 0)
              && inspected.horizontalOverflow <= 2
              && (route.target === 'docs' || (missing.length === 0 && unexpected.length === 0));
            result.shell = inspected.shell;
            result.navigation = {
              links: inspected.links,
              missing,
              unexpected,
              duplicateHrefs: inspected.duplicateHrefs,
              accountHrefs: inspected.accountHrefs,
              expectedOrder: inspected.expectedOrder,
              actualOrder: inspected.actualOrder,
              orderMismatches: inspected.orderMismatches,
              labelMismatches: inspected.labelMismatches,
            };
            result.brand = {
              refs: inspected.brandRefs,
              expected: inspected.expectedBrandRequirements,
              missing: inspected.missingCanonicalRefs,
              staleRefs: inspected.staleRefs,
            };
            result.horizontalOverflow = inspected.horizontalOverflow;
            result.title = inspected.title;
            if (!route.expectedStatuses.includes(status)) result.failure = `Expected HTTP ${route.expectedStatuses.join(' or ')}, received ${status}`;
            if (inspected.shell !== route.target) result.failure = `Expected ${route.target} shell, received ${inspected.shell || 'none'}`;
            if (missing.length || unexpected.length) result.failure = `Navigation mismatch: ${JSON.stringify({ missing, unexpected })}`;
            if (route.target !== 'docs' && inspected.orderMismatches.length) result.failure = `Navigation order mismatch: ${JSON.stringify(inspected.orderMismatches)}`;
            if (route.target !== 'docs' && inspected.labelMismatches.length) result.failure = `Navigation label mismatch: ${JSON.stringify(inspected.labelMismatches)}`;
            if (inspected.staleRefs.length) result.failure = `Legacy brand references: ${inspected.staleRefs.join(', ')}`;
            if (inspected.missingCanonicalRefs.length) result.failure = `Missing canonical brand references: ${inspected.missingCanonicalRefs.join(', ')}`;
            if (inspected.horizontalOverflow > 2) result.failure = `Horizontal overflow: ${inspected.horizontalOverflow}px`;
          } catch (error) {
            result.passed = false;
            result.failure = error instanceof Error ? error.message : String(error);
          }
          result.errors = {
            console: consoleErrors.slice(errorsBefore.console),
            page: pageErrors.slice(errorsBefore.page),
            requests: requestFailures.slice(errorsBefore.request),
            http: httpErrors.slice(errorsBefore.http).filter((item) => !(item.resourceType === 'document' && route.expectedStatuses.includes(item.status))),
          };
          const expectedNotFoundConsole = result.status === 404
            && result.errors.console.every((message) => message.includes('Failed to load resource'));
          const actionableRequests = result.errors.requests.filter((message) => !message.includes('ERR_ABORTED'));
          result.errors.ignoredRequests = result.errors.requests.filter((message) => message.includes('ERR_ABORTED'));
          if ((result.errors.console.length && !expectedNotFoundConsole) || result.errors.page.length || actionableRequests.length || result.errors.http.length) result.passed = false;
          results.push(result);
          process.stdout.write(`${result.passed ? 'PASS' : 'FAIL'} ${auth.id}/${viewport.id}/${route.id}\n`);
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }
  return { skipped, docsRoutes: docsRoutes.map((route) => route.id), results, passed: results.every((result) => result.passed) };
}

const sourceResult = await sourceAudit();
const runtimeResult = await runtimeAudit().catch((error) => ({ passed: false, error: error instanceof Error ? error.message : String(error), results: [] }));
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  docsBaseUrl: docsBaseUrl || null,
  sourceOnly,
  authStates: authStateSpecs().map(({ id }) => id),
  routeManifest: navigationBrandAuditRoutes,
  source: sourceResult,
  runtime: runtimeResult,
  passed: sourceResult.passed && (runtimeResult.skipped === true || runtimeResult.passed === true),
};
await mkdir(outputDir, { recursive: true });
await writeFile(join(outputDir, 'latest-audit.json'), `${JSON.stringify(report)}\n`, 'utf8');
const lines = [
  '# Navigation and brand audit',
  '',
  `- Generated: ${report.generatedAt}`,
  `- Result: **${report.passed ? 'PASS' : 'FAIL'}**`,
  `- Portal/Forgejo base: \`${baseUrl}\``,
  `- Docs base: \`${docsBaseUrl || 'not configured'}\``,
  `- Auth states: ${report.authStates.join(', ')}`,
  '',
  '## Source checks',
  '',
  ...sourceResult.checks.map((item) => `- ${item.passed ? 'PASS' : 'FAIL'} — ${item.name}`),
  '',
  '## Runtime checks',
  '',
  ...(runtimeResult.skipped === true
    ? [`- SKIP — ${runtimeResult.reason}`]
    : runtimeResult.error
      ? [`- FAIL — ${runtimeResult.error}`]
      : [
        ...(Array.isArray(runtimeResult.skipped)
          ? runtimeResult.skipped.map((route) => `- SKIP — ${route}`)
          : []),
        ...runtimeResult.results.map((item) => `- ${item.passed ? 'PASS' : 'FAIL'} — ${item.auth}/${item.viewport}/${item.route}`),
      ]),
  '',
  'The JSON file contains route, shell, auth state, viewport, navigation, brand, overflow, and browser-error details. This audit intentionally writes no screenshots.',
  '',
];
await writeFile(join(outputDir, 'REPORT.md'), `${lines.join('\n')}\n`, 'utf8');

if (!report.passed) process.exitCode = 1;
