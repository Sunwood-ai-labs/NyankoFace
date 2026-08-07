import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.I18N_QA_OUTPUT_DIR || join(root, 'artifacts', 'i18n'));
const routes = [
  ['home', '/'],
  ['models', '/models'],
  ['datasets', '/datasets'],
  ['spaces', '/spaces'],
  ['skills', '/skills'],
  ['mcps', '/mcps'],
  ['prompts', '/prompts'],
  ['knowledge', '/docs'],
  ['characters', '/characters'],
  ['new', '/new?type=doc'],
  ['repository', '/nyankoface/repository-polish-skill'],
  ['files', '/nyankoface/mystic-git-auto-commit?tab=files&revision=v4.2'],
];
const locales = [
  { id: 'ja', expected: ['Models', 'Datasets', 'Knowledge', 'Characters'] },
  { id: 'en', expected: ['Models', 'Datasets', 'Knowledge', 'Characters'] },
];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

for (const locale of locales) {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport, ignoreHTTPSErrors: true });
    await context.addCookies([{ name: 'nyankoface-locale', value: locale.id, url: baseUrl }]);
    for (const [id, path] of routes) {
      const page = await context.newPage();
      const consoleErrors = [];
      page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
      const response = await page.goto(`${baseUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      await page.waitForTimeout(500);
      if (viewport.id === 'mobile') {
        const menu = page.locator('details.xl\\:hidden > summary');
        if (await menu.count()) await menu.first().click();
      }
      const audit = await page.evaluate(() => ({
        lang: document.documentElement.lang,
        text: document.body.innerText,
        viewportWidth: document.documentElement.clientWidth,
        scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      }));
      const screenshot = join(outputDir, 'screenshots', `${id}-${locale.id}-${viewport.id}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      results.push({
        route: id,
        path,
        locale: locale.id,
        viewport: viewport.id,
        status: response?.status() || 0,
        lang: audit.lang,
        expectedNavigationFound: locale.expected.every((label) => audit.text.includes(label)),
        horizontalOverflow: Math.max(0, audit.scrollWidth - audit.viewportWidth),
        consoleErrors,
        screenshot,
      });
      await page.close();
    }
    await context.close();
  }
}

await browser.close();
const failures = results.filter((result) => result.status >= 400 || result.lang !== result.locale || !result.expectedNavigationFound || result.horizontalOverflow > 1 || result.consoleErrors.length);
const report = { generatedAt: new Date().toISOString(), baseUrl, routes: routes.length, cases: results.length, failures, results };
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({ outputDir, cases: results.length, failures: failures.length }, null, 2));
if (failures.length) process.exitCode = 1;
