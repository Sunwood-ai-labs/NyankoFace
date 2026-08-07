import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'http://localhost:8090').replace(/\/$/, '');
const expectedAppName = process.env.EXPECTED_APP_NAME || 'NyankoFace';
const outputDir = resolve(process.env.APP_NAME_QA_OUTPUT_DIR || join(root, 'artifacts', 'app-name'));
const routes = [
  {
    id: 'portal-home',
    path: '/',
    brandSelector: 'header a span:last-child',
    searchSelector: 'header input[type="search"]',
  },
  {
    id: 'forgejo-login',
    path: '/git/user/login',
    brandSelector: '#navbar-logo .nyankoface-logo-word',
    searchSelector: '#navbar .nyankoface-hf-search input[type="search"]',
    metaSelector: 'meta[name="nyankoface-app-name"]',
  },
];
const viewports = [
  { id: 'desktop', width: 1440, height: 900 },
  { id: 'mobile', width: 390, height: 844 },
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport,
      ignoreHTTPSErrors: true,
      reducedMotion: 'reduce',
    });
    for (const route of routes) {
      const page = await context.newPage();
      const response = await page.goto(`${baseUrl}${route.path}`, {
        waitUntil: 'domcontentloaded',
        timeout: 30_000,
      });
      await page.waitForTimeout(500);
      const audit = await page.evaluate(({ brandSelector, searchSelector, metaSelector }) => {
        const brand = document.querySelector(brandSelector);
        const search = document.querySelector(searchSelector);
        const meta = metaSelector ? document.querySelector(metaSelector) : null;
        return {
          title: document.title,
          brand: brand?.textContent?.trim() || '',
          searchLabel: search?.getAttribute('aria-label') || '',
          metaAppName: meta?.getAttribute('content') || '',
          viewportWidth: document.documentElement.clientWidth,
          scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        };
      }, route);
      const defects = [];
      if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
      if (audit.brand !== expectedAppName) defects.push(`brand is "${audit.brand}"`);
      if (!audit.title.includes(expectedAppName)) defects.push(`title is "${audit.title}"`);
      if (route.metaSelector && audit.metaAppName !== expectedAppName) defects.push(`meta app name is "${audit.metaAppName}"`);
      if (route.id === 'portal-home' && !audit.searchLabel.includes(expectedAppName)) defects.push(`search label is "${audit.searchLabel}"`);
      if (audit.scrollWidth > audit.viewportWidth + 1) defects.push(`horizontal overflow ${audit.scrollWidth - audit.viewportWidth}px`);
      const screenshot = join(outputDir, 'screenshots', `${route.id}--${viewport.id}.png`);
      await page.screenshot({ path: screenshot, fullPage: false });
      results.push({ route: route.id, viewport, status: response?.status() || 0, audit, defects, screenshot });
      process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${route.id} ${viewport.id} "${expectedAppName}"\n`);
      await page.close();
    }
    await context.close();
  }
} finally {
  await browser.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  expectedAppName,
  cases: results.length,
  failures: results.filter(({ defects }) => defects.length).length,
  results,
};
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
if (report.failures) process.exitCode = 1;
