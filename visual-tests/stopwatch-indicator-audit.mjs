import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.STOPWATCH_QA_OUTPUT_DIR || join(root, '..', 'docs', 'evidence', 'issues', '42'),
);
const viewports = [
  { id: 'desktop', width: 1440, height: 900 },
  { id: 'mobile', width: 390, height: 844 },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      colorScheme: 'light',
      reducedMotion: 'reduce',
    });
    const page = await context.newPage();
    await page.goto(`${baseUrl}/git/user/login`, { waitUntil: 'domcontentloaded' });
    await page.locator('input[name="user_name"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await Promise.all([
      page.waitForLoadState('domcontentloaded'),
      page.getByRole('button', { name: /log in|login/i }).click(),
    ]);
    await page.goto(`${baseUrl}/git/`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(800);

    const audit = await page.evaluate(() => {
      const trigger = document.querySelector('#navbar a.active-stopwatch-trigger.item');
      const dot = document.querySelector('#navbar .header-stopwatch-dot');
      const profile = document.querySelector('#navbar .user-menu, #navbar [data-tooltip-content*="profile" i]');
      const transparentInteractiveControls = Array.from(
        document.querySelectorAll('#navbar a, #navbar button, #navbar [role="button"], #navbar [tabindex]'),
      ).filter((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        if (rect.width < 1 || rect.height < 1 || style.display === 'none' || style.visibility === 'hidden') return false;
        const background = style.backgroundColor;
        const hasVisibleContent = Boolean(
          element.textContent?.trim()
          || element.querySelector('svg:not([hidden]), img:not([hidden])'),
        );
        return style.opacity === '0'
          || style.color === 'transparent'
          || (!hasVisibleContent && (background === 'transparent' || background === 'rgba(0, 0, 0, 0)'));
      }).map((element) => ({
        tag: element.tagName.toLowerCase(),
        className: element.className?.toString() || '',
        ariaLabel: element.getAttribute('aria-label'),
        title: element.getAttribute('title'),
      }));
      return {
        triggerPresent: Boolean(trigger),
        dotPresent: Boolean(dot),
        profilePresent: Boolean(profile),
        transparentInteractiveControls,
        horizontalOverflow: Math.max(
          0,
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      };
    });
    const defects = [];
    if (audit.triggerPresent) defects.push('inactive stopwatch trigger remains in the DOM');
    if (audit.dotPresent) defects.push('inactive stopwatch dot remains in the DOM');
    if (audit.transparentInteractiveControls.length) {
      defects.push(`${audit.transparentInteractiveControls.length} transparent interactive control(s) remain`);
    }
    if (audit.horizontalOverflow > 2) defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);

    const screenshot = `${viewport.id}--navbar-without-invisible-control.png`;
    await page.screenshot({ path: join(outputDir, screenshot), fullPage: false });
    results.push({ viewport, audit, defects, screenshot });
    process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${viewport.id} stopwatch indicator\n`);
    await context.close();
  }
} finally {
  await browser.close();
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(
  join(outputDir, 'report.json'),
  `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`,
);
if (passed !== results.length) process.exitCode = 1;
