import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generateContactSheets } from './contact-sheets.mjs';
import { routes, themes, viewports } from './routes.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.SCROLL_QA_OUTPUT_DIR || join(root, 'artifacts', 'scroll-audit'));
const concurrency = Math.max(1, Number(process.env.SCROLL_QA_CONCURRENCY || 4));
const select = (values, envName) => {
  const ids = process.env[envName]?.split(',').map((value) => value.trim()).filter(Boolean);
  return ids ? values.filter(({ id }) => ids.includes(id)) : values;
};
const selectedThemes = select(themes, 'VISUAL_QA_THEMES');
const selectedViewports = select(viewports, 'VISUAL_QA_VIEWPORTS');
const selectedRoutes = select(routes, 'VISUAL_QA_ROUTES');
const basePositions = ['top', 'middle', 'bottom'];

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

const inspectViewport = ({ themeId, themeAware }) => {
  const parseColor = (value) => {
    const parts = value.match(/[\d.]+/g)?.map(Number) || [];
    return parts.length >= 3 ? { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 } : null;
  };
  const viewport = { width: document.documentElement.clientWidth, height: window.innerHeight };
  const lightSurfaces = [];
  if (themeId === 'cyberpunk' && themeAware) {
    const explicitThemeSurfaces = new Set([
      'nyankoface-dataset-viewer', 'nyankoface-provider-card', 'nyankoface-model-chip-grid',
      'nyankoface-dataset-selectors', 'nyankoface-dataset-table',
    ]);
    const selectors = [
      '.page-content', '.ui.segment', '.ui.attached.segment', 'article', 'section',
      '.card', '.nyankoface-dataset-viewer', '.nyankoface-provider-card',
      '.nyankoface-model-chip-grid', '.nyankoface-dataset-selectors', 'table',
    ].join(',');
    for (const element of document.querySelectorAll(selectors)) {
      const rect = element.getBoundingClientRect();
      if (rect.right <= 0 || rect.left >= viewport.width || rect.bottom <= 0 || rect.top >= viewport.height) continue;
      const visibleWidth = Math.min(rect.right, viewport.width) - Math.max(rect.left, 0);
      const visibleHeight = Math.min(rect.bottom, viewport.height) - Math.max(rect.top, 0);
      const isExplicitSurface = [...element.classList].some((name) => explicitThemeSurfaces.has(name));
      const minimumArea = isExplicitSurface ? 0.02 : 0.08;
      if (visibleWidth * visibleHeight < viewport.width * viewport.height * minimumArea) continue;
      const style = getComputedStyle(element);
      const color = parseColor(style.backgroundColor);
      if (!color || color.a < 0.9 || Math.min(color.r, color.g, color.b) < 225) continue;
      lightSurfaces.push({
        tag: element.tagName.toLowerCase(),
        className: String(element.className || '').slice(0, 100),
        background: style.backgroundColor,
        area: Math.round(visibleWidth * visibleHeight),
      });
    }
  }
  const primaryRail = document.querySelector('main[data-nyankoface-page-frame], .page-content');
  const primaryRailRect = primaryRail?.getBoundingClientRect();
  const primaryRailStyle = primaryRail ? getComputedStyle(primaryRail) : null;
  const leftInset = primaryRailRect && primaryRailStyle
    ? primaryRailRect.left + (Number.parseFloat(primaryRailStyle.paddingLeft) || 0)
    : null;
  const rightInset = primaryRailRect && primaryRailStyle
    ? viewport.width - primaryRailRect.right + (Number.parseFloat(primaryRailStyle.paddingRight) || 0)
    : null;
  return {
    scrollY: Math.round(Math.max(window.scrollY, document.documentElement.scrollTop, document.body.scrollTop)),
    scrollHeight: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight),
    lightSurfaces: lightSurfaces.slice(0, 8),
    horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - viewport.width),
    primaryRail: primaryRail ? {
      selector: primaryRail.matches('main[data-nyankoface-page-frame]') ? 'portal-main' : 'forgejo-page-content',
      leftInset: Math.round(leftInset),
      rightInset: Math.round(rightInset),
      minimumInset: Math.round(Math.min(leftInset, rightInset)),
    } : null,
  };
};

const captureRoute = async ({ context, route, theme, viewport }) => {
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  let response = null;
  let navigationError = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      response = await page.goto(`${baseUrl}${route.path}`, {
        waitUntil: 'domcontentloaded',
        timeout: 20_000,
      });
      navigationError = null;
      break;
    } catch (error) {
      navigationError = error;
      if (attempt < 2) await page.waitForTimeout(750 * (attempt + 1));
    }
  }
  if (!response) throw navigationError || new Error(`Navigation failed for ${route.path}`);
  await page.waitForTimeout(route.settleMs || 650);
  if (response.status() >= 500) {
    response = await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(Math.max(route.settleMs || 650, 1_500));
  }

  await page.evaluate(() => document.fonts?.ready);
  const pageMetrics = await page.evaluate(() => {
    const root = document.body.scrollHeight > document.documentElement.scrollHeight ? document.body : document.documentElement;
    return { height: window.innerHeight, maxScroll: Math.max(0, root.scrollHeight - root.clientHeight), root: root === document.body ? 'body' : 'document' };
  });
  const scrollTargets = {
    top: 0,
    middle: Math.round(pageMetrics.maxScroll / 2),
    bottom: pageMetrics.maxScroll,
  };
  for (const checkpoint of route.scrollSelectors || []) {
    scrollTargets[checkpoint.id] = await page.locator(checkpoint.selector).first().evaluate((element) => {
      const rect = element.getBoundingClientRect();
      const current = Math.max(window.scrollY, document.documentElement.scrollTop, document.body.scrollTop);
      return Math.max(0, Math.round(current + rect.top - Math.max(16, (window.innerHeight - Math.min(rect.height, window.innerHeight)) / 2)));
    });
  }
  const routeResults = [];
  for (const [position, scrollTarget] of Object.entries(scrollTargets)) {
    await page.evaluate(({ y, root }) => {
      if (root === 'body') document.body.scrollTop = y;
      else window.scrollTo(0, y);
    }, { y: scrollTarget, root: pageMetrics.root });
    await page.waitForTimeout(120);
    const screenshotName = `${theme.id}--${viewport.id}--${route.id}--${position}.png`;
    const screenshotPath = join(outputDir, 'screenshots', screenshotName);
    await page.screenshot({ path: screenshotPath });
    const state = await page.evaluate(inspectViewport, { themeId: theme.id, themeAware: route.themeAware !== false });
    const defects = [];
    const requiredInset = viewport.width < 768 ? 20 : 24;
    if (response.status() >= 400) defects.push(`HTTP ${response.status()}`);
    if (state.horizontalOverflow > 2) defects.push(`Horizontal overflow: ${state.horizontalOverflow}px`);
    if (!route.allowFullBleed && !state.primaryRail) defects.push('Primary content rail is missing');
    if (!route.allowFullBleed && state.primaryRail?.minimumInset < requiredInset) {
      defects.push(`Content safe area: ${state.primaryRail.minimumInset}px; expected at least ${requiredInset}px`);
    }
    if (state.lightSurfaces.length) defects.push(`${state.lightSurfaces.length} large light surface(s) in Cyberpunk`);
    if (pageErrors.length) defects.push(`${pageErrors.length} page error(s)`);
    const result = {
      route: {
        id: `${route.id}--${position}`,
        label: `${route.label} · ${position}`,
        path: route.path,
        focus: `${route.focus}; ${position} viewport slice`,
      },
      theme,
      viewport,
      position,
      status: response.status(),
      screenshot: relative(outputDir, screenshotPath).replaceAll('\\', '/'),
      ...state,
      defects,
      passed: defects.length === 0,
    };
    routeResults.push(result);
    process.stdout.write(`${result.passed ? 'PASS' : 'FAIL'} ${theme.id.padEnd(10)} ${viewport.id.padEnd(7)} ${route.id.padEnd(28)} ${position}\n`);
  }
  await page.close();
  return routeResults;
};

try {
  for (const theme of selectedThemes) {
    for (const viewport of selectedViewports) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: theme.colorScheme,
        reducedMotion: 'reduce',
      });
      await context.addInitScript((themeId) => {
        localStorage.setItem('nyankoface-theme-v2', themeId);
        localStorage.setItem('nyankoface-theme', themeId);
        document.cookie = `nyankoface-theme=${themeId}; Path=/; Max-Age=31536000; SameSite=Lax`;
      }, theme.id);
      let nextIndex = 0;
      const workers = Array.from({ length: Math.min(concurrency, selectedRoutes.length) }, async () => {
        while (nextIndex < selectedRoutes.length) {
          const route = selectedRoutes[nextIndex];
          nextIndex += 1;
          results.push(...await captureRoute({ context, route, theme, viewport }));
        }
      });
      await Promise.all(workers);
      await context.close();
    }
  }
} finally {
  await browser.close();
}

results.sort((a, b) =>
  a.theme.id.localeCompare(b.theme.id) ||
  a.viewport.id.localeCompare(b.viewport.id) ||
  a.route.id.localeCompare(b.route.id));
const manifest = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  dimensions: {
    themes: selectedThemes.map(({ id }) => id),
    viewports: selectedViewports.map(({ id, width, height }) => ({ id, width, height })),
    routes: selectedRoutes.flatMap((route) => [...basePositions, ...(route.scrollSelectors || []).map(({ id }) => id)].map((position) => ({ id: `${route.id}--${position}`, path: route.path }))),
  },
  summary: {
    total: results.length,
    passed: results.filter(({ passed }) => passed).length,
    failed: results.filter(({ passed }) => !passed).length,
  },
  results,
};
await writeFile(join(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
const sheets = await generateContactSheets({ manifest, outputDir });
const report = [
  '# Scroll visual audit', '',
  `Result: **${manifest.summary.passed}/${manifest.summary.total} passed**`, '',
  `Coverage: **${selectedThemes.length} themes × ${selectedViewports.length} viewports × ${selectedRoutes.length} routes × top/middle/bottom plus semantic checkpoints = ${results.length} screenshots**`, '',
  `Contact sheets: **${sheets.length}**`, '',
  ...results.filter(({ passed }) => !passed).flatMap((result) => [
    `## ${result.theme.id} / ${result.viewport.id} / ${result.route.label}`,
    '', `- ${result.defects.join('; ')}`, `- Light surfaces: \`${JSON.stringify(result.lightSurfaces)}\``, '',
    `![${result.route.label}](${result.screenshot})`, '',
  ]),
];
await writeFile(join(outputDir, 'SCROLL_AUDIT.md'), `${report.join('\n')}\n`);
process.stdout.write(`\nScroll audit: ${manifest.summary.passed}/${manifest.summary.total} passed; ${sheets.length} contact sheets\n`);
if (manifest.summary.failed) process.exitCode = 1;
