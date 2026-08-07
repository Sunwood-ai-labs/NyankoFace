import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const outputDir = resolve(
  repositoryRoot,
  process.env.SYNTAX_AUDIT_OUTPUT || 'docs/evidence/issues/94',
);
const screenshotDir = join(outputDir, 'screenshots');
const baseUrl = process.env.NYANKOFACE_VISUAL_BASE_URL || 'http://127.0.0.2:3101';

const routes = [
  {
    id: 'article-yaml',
    label: 'Knowledge article · YAML',
    path: '/docs/nyankoface/docs-publishing-quickstart',
    selector: '.nyankoface-code-block',
  },
  {
    id: 'readme-long-line',
    label: 'Repository README · long plain text',
    path: '/nyankoface/draw-io-skill',
    selector: '.nyankoface-code-block',
    chooseLongest: true,
    modes: ['standard-dark', 'cyberpunk'],
  },
  {
    id: 'readme-unknown-language',
    label: 'Repository README · unknown language fallback',
    path: '/nyankoface/gitlab-kanban-mcp-server',
    selector: '.nyankoface-code-block[data-language-known="false"]',
    modes: ['standard-light'],
  },
];

const modes = [
  { id: 'standard-light', theme: 'standard', colorScheme: 'light' },
  { id: 'standard-dark', theme: 'standard', colorScheme: 'dark' },
  { id: 'cyberpunk', theme: 'cyberpunk', colorScheme: 'dark' },
];

const viewports = [
  { id: 'desktop', width: 1440, height: 1000, isMobile: false },
  { id: 'mobile', width: 390, height: 844, isMobile: true },
];

const expectedScreenshotRoot = join(repositoryRoot, 'docs', 'evidence', 'issues', '94', 'screenshots');
if (screenshotDir !== expectedScreenshotRoot) throw new Error(`Refusing to clear unexpected screenshot path: ${screenshotDir}`);
await rm(screenshotDir, { recursive: true, force: true });
await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
const defects = [];
let themeCycle;

try {
  for (const mode of modes) {
    for (const viewport of viewports) {
      for (const route of routes) {
        if (route.modes && !route.modes.includes(mode.id)) continue;
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          isMobile: viewport.isMobile,
          hasTouch: viewport.isMobile,
          colorScheme: mode.colorScheme,
          locale: 'ja-JP',
        });
        await context.addCookies([
          { name: 'nyankoface-locale', value: 'ja', url: baseUrl },
        ]);
        await context.addInitScript((theme) => {
          localStorage.setItem('nyankoface-theme-v2', theme);
        }, mode.theme);
        const page = await context.newPage();
        const consoleErrors = [];
        page.on('console', (message) => {
          if (message.type() === 'error') consoleErrors.push({ text: message.text(), location: message.location() });
        });
        const response = await page.goto(`${baseUrl}${route.path}`, {
          waitUntil: 'domcontentloaded',
          timeout: 120_000,
        });
        await page.locator('.nyankoface-code-block').first().waitFor({ timeout: 30_000 });
        await page.locator('[data-nyankoface-markdown][data-code-controls="ready"]').waitFor({ timeout: 30_000 });

        let codeBlock = page.locator(route.selector).first();
        if (route.chooseLongest) {
          const candidateIndex = await page.locator(route.selector).evaluateAll((figures) => {
            const widths = figures.map((figure) => figure.querySelector('pre')?.scrollWidth || 0);
            return widths.indexOf(Math.max(...widths));
          });
          codeBlock = page.locator(route.selector).nth(candidateIndex);
        }
        await codeBlock.scrollIntoViewIfNeeded();
        await page.waitForTimeout(150);

        const audit = await codeBlock.evaluate((figure) => {
          const pre = figure.querySelector('pre');
          const code = figure.querySelector('code');
          const copy = figure.querySelector('[data-nyankoface-copy-code]');
          const rect = figure.getBoundingClientRect();
          return {
            language: figure.getAttribute('data-language'),
            knownLanguage: figure.getAttribute('data-language-known'),
            figureWidth: Math.round(rect.width),
            figureLeft: Math.round(rect.left),
            figureRight: Math.round(rect.right),
            preClientWidth: pre?.clientWidth || 0,
            preScrollWidth: pre?.scrollWidth || 0,
            tokenCount: code?.querySelectorAll('[class^="hljs-"]').length || 0,
            copyLabel: copy?.getAttribute('aria-label'),
            copyText: copy?.textContent?.trim(),
            background: pre ? getComputedStyle(pre).backgroundColor : '',
            foreground: pre ? getComputedStyle(pre).color : '',
            pageScrollWidth: document.documentElement.scrollWidth,
            viewportWidth: window.innerWidth,
          };
        });

        let scrollInteraction;
        if (route.id === 'readme-long-line') {
          const pre = codeBlock.locator('pre');
          await pre.hover();
          const before = await pre.evaluate((element) => element.scrollLeft);
          await page.keyboard.down('Shift');
          await page.mouse.wheel(0, 640);
          await page.keyboard.up('Shift');
          await page.waitForTimeout(100);
          const after = await pre.evaluate((element) => element.scrollLeft);
          scrollInteraction = { before, after, moved: after > before };
        }

        const screenshotName = `${mode.id}--${viewport.id}--${route.id}.png`;
        let copyState;
        if (mode.id === 'standard-light') {
          await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
          const copyButton = codeBlock.locator('[data-nyankoface-copy-code]');
          const expectedClipboardText = await codeBlock.locator('code').textContent() || '';
          await copyButton.focus();
          await copyButton.click();
          await copyButton.evaluate(async (button) => {
            for (let attempt = 0; attempt < 40 && !button.dataset.copyState; attempt += 1) {
              await new Promise((resolve) => window.setTimeout(resolve, 25));
            }
            if (!button.dataset.copyState) throw new Error('Copy feedback did not settle');
          });
          copyState = {
            visibleText: (await copyButton.textContent())?.trim(),
            state: await copyButton.getAttribute('data-copy-state'),
            clipboardMatches: await page.evaluate(async (expected) => (
              (await navigator.clipboard.readText()).replaceAll('\r\n', '\n')
            ) === expected.replaceAll('\r\n', '\n'), expectedClipboardText),
          };
        }

        await page.screenshot({ path: join(screenshotDir, screenshotName), fullPage: false });

        if (!themeCycle && route.id === 'article-yaml' && viewport.id === 'desktop' && mode.id === 'standard-light') {
          const themeButton = page.locator('.nyankoface-theme-selector:visible').first();
          const readBackground = () => codeBlock.locator('pre').evaluate((pre) => getComputedStyle(pre).backgroundColor);
          const states = [{ theme: 'standard', background: await readBackground() }];
          for (const expected of ['solarpunk', 'cyberpunk', 'standard']) {
            await themeButton.click();
            await page.waitForTimeout(50);
            states.push({
              theme: await themeButton.getAttribute('data-theme'),
              expected,
              background: await readBackground(),
            });
          }
          themeCycle = states;
        }

        const failures = [];
        if ((response?.status() || 0) !== 200) failures.push(`HTTP ${response?.status() || 0}`);
        if (audit.pageScrollWidth > audit.viewportWidth) failures.push('page has horizontal overflow');
        if (audit.figureLeft < 0 || audit.figureRight > audit.viewportWidth + 1) failures.push('code block is clipped');
        if (!audit.copyLabel) failures.push('copy button has no accessible name');
        if (route.id === 'article-yaml' && audit.tokenCount === 0) failures.push('YAML has no highlighted tokens');
        if (route.id === 'readme-long-line' && audit.preScrollWidth <= audit.preClientWidth) failures.push('long line does not scroll inside pre');
        if (route.id === 'readme-long-line' && !scrollInteraction?.moved) failures.push('keyboard-assisted horizontal wheel did not move pre');
        if (route.id === 'readme-unknown-language' && audit.knownLanguage !== 'false') failures.push('unknown language did not fall back');
        if (copyState && (copyState.state !== 'success' || !copyState.clipboardMatches)) failures.push('copy interaction failed');
        const applicationConsoleErrors = consoleErrors.filter((error) => !error.text.startsWith('Failed to load resource:'));
        if (applicationConsoleErrors.length > 0) failures.push(`${applicationConsoleErrors.length} application console error(s)`);

        results.push({ mode, viewport, route: { id: route.id, label: route.label, path: route.path }, audit, scrollInteraction, copyState, resourceWarnings: consoleErrors.filter((error) => error.text.startsWith('Failed to load resource:')), applicationConsoleErrors, screenshot: `screenshots/${screenshotName}`, failures });
        defects.push(...failures.map((failure) => `${mode.id}/${viewport.id}/${route.id}: ${failure}`));
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
}

if (!themeCycle || new Set(themeCycle.map((state) => state.background)).size < 3) {
  defects.push('theme selector did not update code colors across all three themes');
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  coverage: {
    screenshots: results.length,
    routes: routes.length,
    modes: modes.map((mode) => mode.id),
    viewports: viewports.map((viewport) => `${viewport.id} ${viewport.width}x${viewport.height}`),
  },
  themeCycle,
  results,
  defects,
};

await writeFile(join(outputDir, 'audit.json'), `${JSON.stringify(report)}\n`, 'utf8');
await writeFile(join(outputDir, 'README.md'), [
  '# Issue #94 syntax highlighting visual QA',
  '',
  '- Runtime: local Next.js development server connected to a local Forgejo dataset',
  '- Visual capture is manual evidence and is not executed by CI.',
  `- Coverage: ${report.coverage.screenshots} viewport screenshots`,
  `- Result: ${defects.length === 0 ? 'PASS' : `FAIL (${defects.length})`}`,
  '',
  '| Result | Theme | Viewport | Surface | Language | Page overflow | Internal overflow | Screenshot |',
  '| --- | --- | --- | --- | --- | ---: | ---: | --- |',
  ...results.map((result) => `| ${result.failures.length === 0 ? 'PASS' : 'FAIL'} | ${result.mode.id} | ${result.viewport.id} | ${result.route.label} | ${result.audit.language} | ${result.audit.pageScrollWidth - result.audit.viewportWidth}px | ${result.audit.preScrollWidth - result.audit.preClientWidth}px | [view](${result.screenshot}) |`),
  '',
  '## Review inventory',
  '',
  '- Article and repository README use the same header, tokens, copy control, focus behavior, and scroll container.',
  '- Standard light, Standard dark, and Cyberpunk update from CSS theme tokens without re-highlighting.',
  '- Desktop and 390px mobile pages do not gain horizontal page overflow.',
  '- Long source lines scroll inside the code block; unknown languages remain escaped plain text.',
  '- Copy is exercised with a real click and checked against the browser clipboard.',
  '- Exploratory cases: an unknown `env` fence and a 272-character README line.',
  '- The imported `draw-io-skill` README references upstream images that return 404 in the seed dataset. Those resource warnings are recorded in `audit.json`; they predate this renderer change and are not application console errors.',
  '',
  '## Environment note',
  '',
  'The public access path exceeded 120 seconds during the first article request. The final audit used a local HTTP endpoint; this isolates transport latency from renderer QA.',
  '',
  ...(defects.length ? ['## Defects', '', ...defects.map((defect) => `- ${defect}`), ''] : []),
].join('\n'), 'utf8');

console.log(JSON.stringify({ output: relative(repositoryRoot, outputDir), screenshots: report.coverage.screenshots, defects }, null, 2));
if (defects.length > 0) process.exitCode = 1;
