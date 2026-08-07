import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.THEME_SELECTOR_QA_OUTPUT_DIR || join(root, 'artifacts', 'theme-selector'));
const cases = [
  { id: 'desktop', viewport: { width: 1440, height: 900 } },
  { id: 'mobile', viewport: { width: 390, height: 844 } },
];
const sequence = [
  { active: 'standard', nextEn: 'Switch to Solarpunk', nextJa: 'ソーラーパンクへ切り替える' },
  { active: 'solarpunk', nextEn: 'Switch to Cyberpunk', nextJa: 'サイバーパンクへ切り替える' },
  { active: 'cyberpunk', nextEn: 'Switch to Standard', nextJa: 'スタンダードへ切り替える' },
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });

const results = [];
for (const testCase of cases) {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: testCase.viewport,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(8_000);
  const defects = [];

  const initialUrl = testCase.id === 'mobile' ? `${baseUrl}/spaces` : `${baseUrl}/`;
  let response = await page.goto(initialUrl, { waitUntil: 'load' });
  if (response?.status() !== 200) defects.push(`Initial page returned HTTP ${response?.status() ?? 'none'}`);
  await page.evaluate(() => {
    localStorage.setItem('nyankoface-theme-v2', 'standard');
    localStorage.removeItem('nyankoface-theme');
  });
  response = await page.reload({ waitUntil: 'load' });
  if (response?.status() !== 200) defects.push(`Home reload returned HTTP ${response?.status() ?? 'none'}`);

  if (testCase.id === 'mobile') {
    const menuToggle = page.locator('header details > summary:visible');
    if (await menuToggle.count() !== 1) defects.push('Expected one visible mobile menu toggle');
    else await menuToggle.click();
  }

  const button = page.locator('.nyankoface-theme-selector:visible');
  if (await button.count() !== 1) defects.push(`Expected one visible theme button, found ${await button.count()}`);

  const states = [];
  if (defects.length === 0) {
    for (const expected of sequence) {
      const state = await button.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        return {
          active: document.documentElement.dataset.nyankofaceTheme || 'standard',
          ariaLabel: element.getAttribute('aria-label'),
          width: rect.width,
          height: rect.height,
          stored: localStorage.getItem('nyankoface-theme-v2'),
        };
      });
      if (testCase.id === 'mobile' && expected.active === 'cyberpunk') {
        state.menuHighlight = await page.locator('header details[open] > .nyankoface-mobile-menu-toggle').evaluate((element) => {
          const style = getComputedStyle(element);
          const luminance = (value) => {
            const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [0, 0, 0];
            const linear = channels.map((channel) => {
              const normalized = channel / 255;
              return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
          };
          const foreground = luminance(style.color);
          const background = luminance(style.backgroundColor);
          return {
            color: style.color,
            background: style.backgroundColor,
            contrast: Math.round(((Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05)) * 100) / 100,
          };
        });
        if (state.menuHighlight.contrast < 4.5) defects.push(`Mobile menu highlight contrast is ${state.menuHighlight.contrast}:1`);
      }
      if (testCase.id === 'mobile') {
        const activeNavigation = page.locator('.nyankoface-mobile-nav-link[aria-current="page"]');
        if (await activeNavigation.count() !== 1) {
          defects.push(`Expected one current mobile navigation item, found ${await activeNavigation.count()}`);
        } else {
          state.activeNavigation = await activeNavigation.evaluate((element) => {
            const style = getComputedStyle(element);
            const luminance = (value) => {
              const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [0, 0, 0];
              const linear = channels.map((channel) => {
                const normalized = channel / 255;
                return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
              });
              return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
            };
            const foreground = luminance(style.color);
            const background = luminance(style.backgroundColor);
            return {
              label: element.textContent?.trim(),
              color: style.color,
              background: style.backgroundColor,
              contrast: Math.round(((Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05)) * 100) / 100,
            };
          });
          if (state.activeNavigation.label !== 'Spaces') defects.push(`Current mobile navigation label is ${state.activeNavigation.label}`);
          if (state.activeNavigation.contrast < 4.5) defects.push(`Current mobile navigation contrast is ${state.activeNavigation.contrast}:1`);
        }
      }
      states.push(state);
      if (state.active !== expected.active) defects.push(`Expected ${expected.active}, received ${state.active}`);
      if (state.stored !== expected.active) defects.push(`Stored theme should be ${expected.active}, received ${state.stored}`);
      if (!state.ariaLabel?.includes(expected.nextEn) && !state.ariaLabel?.includes(expected.nextJa)) defects.push(`Unexpected aria-label: ${state.ariaLabel}`);
      if (Math.abs(state.width - 32) > 0.1 || Math.abs(state.height - 32) > 0.1) {
        defects.push(`Theme button is ${state.width}×${state.height}, expected 32×32 (±0.1px)`);
      }
      await page.screenshot({ path: join(outputDir, `${testCase.id}--${expected.active}.png`), fullPage: false });
      await button.click();
      await page.waitForTimeout(180);
    }

    await button.click();
    await page.reload({ waitUntil: 'load' });
    const persisted = await page.evaluate(() => ({
      active: document.documentElement.dataset.nyankofaceTheme || 'standard',
      stored: localStorage.getItem('nyankoface-theme-v2'),
      overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - document.documentElement.clientWidth,
    }));
    if (persisted.active !== 'solarpunk' || persisted.stored !== 'solarpunk') defects.push(`Reload did not preserve Solarpunk: ${JSON.stringify(persisted)}`);
    if (persisted.overflow > 2) defects.push(`Horizontal overflow is ${persisted.overflow}px`);
    states.push({ persisted });
  }

  results.push({
    id: testCase.id,
    viewport: testCase.viewport,
    passed: defects.length === 0,
    defects,
    states,
  });
  await context.close();
  await browser.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  passed: results.every(({ passed }) => passed),
  results,
};
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
await writeFile(join(outputDir, 'REPORT.md'), [
  '# Theme selector audit',
  '',
  `- Result: ${report.passed ? 'PASS' : 'FAIL'}`,
  `- Base URL: ${baseUrl}`,
  '',
  ...results.flatMap((result) => [
    `## ${result.id}`,
    '',
    `- ${result.passed ? 'PASS' : 'FAIL'} — 32px icon control, cycle order, persistence, and overflow`,
    ...result.defects.map((defect) => `- FAIL — ${defect}`),
    ...sequence.map(({ active }) => `- Screenshot: ${relative(root, join(outputDir, `${result.id}--${active}.png`)).replaceAll('\\', '/')}`),
    '',
  ]),
].join('\n'));

for (const result of results) {
  process.stdout.write(`${result.passed ? 'PASS' : 'FAIL'} ${result.id} theme selector\n`);
  for (const defect of result.defects) process.stdout.write(`  ${defect}\n`);
}

if (!report.passed) process.exitCode = 1;
