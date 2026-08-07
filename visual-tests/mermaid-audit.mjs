import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(root, '..');
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'http://localhost:8090').replace(/\/$/, '');
const outputDir = resolve(
  process.env.MERMAID_QA_OUTPUT_DIR
    || join(repositoryRoot, 'docs', 'evidence', 'markdown-mermaid', '2026-07-25'),
);
const screenshotDir = join(outputDir, 'screenshots');
const themes = ['standard', 'solarpunk', 'cyberpunk'];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];
const routes = [
  {
    id: 'repository-readme',
    path: '/nyankoface/nyankoface-knowledge',
    expectedRendered: 1,
    expectedFallbacks: 0,
  },
  {
    id: 'knowledge-article',
    path: '/docs/nyankoface/mermaid-rendering-lab',
    expectedRendered: 5,
    expectedFallbacks: 1,
  },
];

await rm(screenshotDir, { recursive: true, force: true });
await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

for (const theme of themes) {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport,
      ignoreHTTPSErrors: true,
      colorScheme: theme === 'cyberpunk' ? 'dark' : 'light',
      reducedMotion: 'no-preference',
    });
    await context.addInitScript((selectedTheme) => {
      localStorage.setItem('nyankoface-theme-v2', selectedTheme);
      document.cookie = `nyankoface-theme=${selectedTheme}; Path=/; Max-Age=31536000; SameSite=Lax`;
    }, theme);

    for (const route of routes) {
      const page = await context.newPage();
      const pageErrors = [];
      const consoleErrors = [];
      const unexpectedHttpErrors = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      page.on('console', (message) => {
        if (message.type() !== 'error') return;
        const text = message.text();
        if (!text.startsWith('Failed to load resource:')) consoleErrors.push(text);
      });
      page.on('response', (httpResponse) => {
        if (httpResponse.status() < 400) return;
        const url = httpResponse.url();
        if (!url.includes('/runner-api/metrics/')) {
          unexpectedHttpErrors.push({ status: httpResponse.status(), url });
        }
      });
      const response = await page.goto(`${baseUrl}${route.path}`, {
        waitUntil: 'networkidle',
        timeout: 45_000,
      });
      await page.waitForFunction(
        (expected) => document.querySelectorAll('[data-mermaid-state="rendered"]').length === expected,
        route.expectedRendered,
        { timeout: 20_000 },
      );
      await page.evaluate(() => document.fonts?.ready).catch(() => undefined);
      await page.evaluate(async () => {
        const step = Math.max(420, Math.floor(window.innerHeight * 0.7));
        for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
          window.scrollTo(0, y);
          await new Promise((resolve) => window.setTimeout(resolve, 45));
        }
        window.scrollTo(0, 0);
      });

      const state = await page.evaluate(() => {
        const figures = Array.from(document.querySelectorAll('.nyankoface-mermaid'));
        return {
          activeTheme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
          rendered: document.querySelectorAll('[data-mermaid-state="rendered"]').length,
          fallbacks: document.querySelectorAll('[data-mermaid-state="error"]').length,
          rawBlocks: document.querySelectorAll('pre > code.language-mermaid').length,
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
          figures: figures.map((figure) => {
            const viewport = figure.querySelector('.nyankoface-mermaid-viewport');
            const box = figure.getBoundingClientRect();
            return {
              state: figure.getAttribute('data-mermaid-state'),
              view: figure.getAttribute('data-mermaid-view'),
              left: box.left,
              right: box.right,
              viewportClientWidth: viewport?.clientWidth || 0,
              viewportScrollWidth: viewport?.scrollWidth || 0,
            };
          }),
        };
      });

      const screenshot = join(screenshotDir, `${theme}--${viewport.id}--${route.id}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      const figureScreenshots = [];
      for (let index = 0; index < state.figures.length; index += 1) {
        const figureScreenshot = join(
          screenshotDir,
          `${theme}--${viewport.id}--${route.id}--diagram-${index + 1}.png`,
        );
        await page.locator('.nyankoface-mermaid').nth(index).screenshot({ path: figureScreenshot });
        figureScreenshots.push(relative(repositoryRoot, figureScreenshot).replaceAll('\\', '/'));
      }

      let zoom = null;
      if (viewport.id === 'mobile' && route.id === 'knowledge-article') {
        const firstFigure = page.locator('.nyankoface-mermaid').first();
        const button = firstFigure.locator('.nyankoface-mermaid-zoom');
        await button.click();
        zoom = await firstFigure.evaluate((figure) => {
          const viewport = figure.querySelector('.nyankoface-mermaid-viewport');
          const button = figure.querySelector('.nyankoface-mermaid-zoom');
          return {
            view: figure.getAttribute('data-mermaid-view'),
            pressed: button?.getAttribute('aria-pressed'),
            label: button?.textContent?.trim(),
            clientWidth: viewport?.clientWidth || 0,
            scrollWidth: viewport?.scrollWidth || 0,
          };
        });
        await firstFigure.screenshot({
          path: join(screenshotDir, `${theme}--mobile--knowledge-article--diagram-1-zoom.png`),
        });
        await button.click();
      }

      const figureBoundsPass = state.figures.every(
        (figure) => figure.left >= -1 && figure.right <= viewport.width + 1,
      );
      const fitPass = state.figures
        .filter((figure) => figure.state === 'rendered')
        .every(
          (figure) => figure.view === 'fit'
            && figure.viewportScrollWidth <= figure.viewportClientWidth + 2,
        );
      const passed = response?.status() === 200
        && state.activeTheme === theme
        && state.rendered === route.expectedRendered
        && state.fallbacks === route.expectedFallbacks
        && state.rawBlocks === 0
        && state.scrollWidth <= state.clientWidth + 1
        && figureBoundsPass
        && fitPass
        && pageErrors.length === 0
        && consoleErrors.length === 0
        && unexpectedHttpErrors.length === 0
        && (!zoom || (
          zoom.view === 'actual'
          && zoom.pressed === 'true'
          && zoom.scrollWidth > zoom.clientWidth
        ));

      results.push({
        theme,
        viewport: viewport.id,
        route: route.id,
        status: response?.status() || 0,
        ...state,
        pageErrors,
        consoleErrors,
        unexpectedHttpErrors,
        figureBoundsPass,
        fitPass,
        zoom,
        screenshot: relative(repositoryRoot, screenshot).replaceAll('\\', '/'),
        figureScreenshots,
        passed,
      });
      await page.close();
    }
    await context.close();
  }
}

await browser.close();
const failures = results.filter((result) => !result.passed);
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  coverage: {
    themes: themes.length,
    viewports: viewports.length,
    routes: routes.length,
    screenshots: results.reduce(
      (count, result) => count + 1 + result.figureScreenshots.length + (result.zoom ? 1 : 0),
      0,
    ),
  },
  failures,
  results,
};
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
await writeFile(join(outputDir, 'REPORT.md'), [
  '# Mermaid visual audit',
  '',
  `- Base URL: \`${baseUrl}\``,
  `- Coverage: ${themes.length} themes × ${viewports.length} viewports × ${routes.length} Markdown surfaces = ${results.length} cases`,
  `- Screenshots: ${report.coverage.screenshots}`,
  `- Result: ${failures.length === 0 ? 'PASS' : 'FAIL'} (${results.length - failures.length}/${results.length})`,
  '- Checks: rendered/fallback counts, raw source removal, responsive fit, optional mobile zoom, theme activation, page errors, console errors, figure bounds, and page overflow.',
  '',
].join('\n'));
console.log(JSON.stringify({
  outputDir,
  cases: results.length,
  screenshots: report.coverage.screenshots,
  failures: failures.length,
}, null, 2));
if (failures.length) {
  console.error(JSON.stringify({ mermaidAuditFailures: failures }, null, 2));
  process.exitCode = 1;
}
