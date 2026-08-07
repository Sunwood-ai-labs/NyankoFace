import { chromium, webkit } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.INTERACTION_QA_OUTPUT_DIR || join(root, 'artifacts', 'interactions'));
const issuePath = '/git/seraphim-labs/qr-code-generator/issues/4';

const cases = [
  { id: 'chromium-desktop', engine: chromium, viewport: { width: 1440, height: 1000 } },
  { id: 'chromium-mobile', engine: chromium, viewport: { width: 390, height: 844 } },
  { id: 'webkit-mobile', engine: webkit, viewport: { width: 390, height: 844 } },
].filter(({ id }) => !process.env.INTERACTION_QA_CASES || process.env.INTERACTION_QA_CASES.split(',').includes(id));

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });

const results = [];

for (const testCase of cases) {
  const browser = await testCase.engine.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: testCase.viewport,
    colorScheme: 'dark',
    reducedMotion: 'reduce',
  });
  if (testCase.engine === chromium) {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: baseUrl });
  }
  const page = await context.newPage();
  page.setDefaultTimeout(8_000);
  page.setDefaultNavigationTimeout(20_000);
  const checks = [];

  const check = async (name, operation) => {
    try {
      const detail = await operation();
      checks.push({ name, passed: true, detail });
      process.stdout.write(`PASS ${testCase.id.padEnd(17)} ${name}\n`);
    } catch (error) {
      checks.push({ name, passed: false, detail: error instanceof Error ? error.message : String(error) });
      process.stdout.write(`FAIL ${testCase.id.padEnd(17)} ${name}\n`);
      process.stdout.write(`  ${checks.at(-1).detail}\n`);
    }
  };
  const expect = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const openIssue = async () => {
    let response = null;
    for (let attempt = 0; attempt < 5; attempt += 1) {
      response = await page.goto(`${baseUrl}${issuePath}`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
      if (response?.status() === 200) break;
      await page.waitForTimeout(750);
    }
    expect(response?.status() === 200, `Issue returned HTTP ${response?.status() ?? 'none'}`);
    await page.waitForTimeout(350);
  };
  const screenshot = async (name, locator = null) => {
    const path = join(outputDir, `${testCase.id}--${name}.png`);
    if (locator) await locator.screenshot({ path });
    else await page.screenshot({ path, fullPage: false });
    return relative(root, path).replaceAll('\\', '/');
  };

  await check('issue loads in automatic Cyberpunk dark theme', async () => {
    await openIssue();
    const theme = await page.locator('html').getAttribute('data-nyankoface-theme');
    expect(theme === 'cyberpunk', `Expected cyberpunk, received ${theme || 'standard'}`);
    await page.waitForFunction(
      () => document.querySelector('.nyankoface-title-kind')?.textContent?.trim() === 'Spaces:',
      undefined,
      { timeout: 5_000 },
    );
    return { theme, repositoryKind: 'Spaces:', screenshot: await screenshot('issue') };
  });

  await check('standard HTML disclosure opens and closes', async () => {
    const summary = page.locator('.comment-body details > summary', { hasText: 'Reviewer note' });
    expect(await summary.count() === 1, 'Expected exactly one Reviewer note summary');
    const semantic = await summary.evaluate((element) => ({
      summaryTag: element.tagName,
      detailsTag: element.parentElement?.tagName,
    }));
    expect(semantic.summaryTag === 'SUMMARY' && semantic.detailsTag === 'DETAILS', 'Disclosure is not native DETAILS/SUMMARY HTML');
    await summary.click();
    expect(await summary.evaluate((element) => element.parentElement?.hasAttribute('open')), 'Disclosure did not open');
    const card = summary.locator('xpath=ancestor::*[contains(@class,"timeline-item")][1]');
    const image = await screenshot('disclosure-open', card);
    await summary.click();
    expect(!(await summary.evaluate((element) => element.parentElement?.hasAttribute('open'))), 'Disclosure did not close');
    return { ...semantic, screenshot: image };
  });

  await check('navigation menu opens without accidental navigation', async () => {
    const toggle = page.locator('#navbar-expand-toggle');
    if (testCase.viewport.width > 767) {
      expect(!(await toggle.isVisible()), 'Mobile menu toggle should be hidden on desktop');
      expect(await page.locator('#navbar a[href="/datasets"]:visible').count() === 1, 'Desktop Datasets navigation is missing');
      expect(await page.locator('#navbar a[href="/spaces"]:visible').count() === 1, 'Desktop Spaces navigation is missing');
      const navColor = await page.locator('#navbar a[href="/datasets"]:visible').evaluate((element) => getComputedStyle(element).color);
      expect(navColor !== 'rgb(0, 0, 0)', 'Desktop navigation text is black on the dark theme');
      const tabState = await page.locator('.secondary-nav a.nyankoface-app-tab:visible').evaluate((element) => ({
        color: getComputedStyle(element).color,
        theme: document.documentElement.getAttribute('data-nyankoface-theme'),
        matches: element.matches('html[data-nyankoface-theme="cyberpunk"] body a.nyankoface-app-tab'),
      }));
      expect(!['rgb(17, 24, 39)', 'rgb(75, 85, 99)'].includes(tabState.color), `Desktop repository tab contrast is too low: ${JSON.stringify(tabState)}`);
      return { mode: 'desktop navigation', navColor, tabState, screenshot: await screenshot('desktop-nav') };
    }
    const before = page.url();
    await toggle.click();
    expect(page.url() === before, `Menu changed URL to ${page.url()}`);
    expect(await page.locator('.nyankoface-mobile-menu-sheet').isVisible(), 'Menu sheet is not visible');
    expect(await toggle.getAttribute('aria-expanded') === 'true', 'Menu aria-expanded is not true');
    const image = await screenshot('nav-open');
    await toggle.click();
    expect(!(await page.locator('.nyankoface-mobile-menu-sheet').isVisible()), 'Menu sheet did not close');
    return { screenshot: image };
  });

  await check('all comment menus open and permalink copy works', async () => {
    const menus = page.locator('[role="menu"][aria-label="Comment menu"]');
    expect(await menus.count() === 4, `Expected 4 comment menus, found ${await menus.count()}`);
    for (let index = 0; index < 4; index += 1) {
      await menus.nth(index).locator(':scope > .context-menu').click();
      const item = menus.nth(index).locator(':scope > .menu [role="menuitem"]');
      expect(await item.count() === 1 && await item.isVisible(), `Comment menu ${index + 1} did not open`);
      if (index === 1) {
        await screenshot('comment-menu-open', menus.nth(index).locator('xpath=ancestor::*[contains(@class,"timeline-item")][1]'));
        await item.click();
      } else {
        await menus.nth(index).locator(':scope > .context-menu').click();
      }
    }
    return { menuCount: 4 };
  });

  await check('all code Copy buttons are visible and report success', async () => {
    const buttons = page.getByRole('button', { name: 'Copy code', exact: true });
    expect(await buttons.count() === 2, `Expected 2 Copy buttons, found ${await buttons.count()}`);
    for (let index = 0; index < 2; index += 1) {
      expect(await buttons.nth(index).isVisible(), `Copy button ${index + 1} is hidden`);
    }
    await buttons.first().click();
    await page.waitForTimeout(150);
    const copiedText = await page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
    if (testCase.engine === chromium) {
      expect(copiedText?.includes('docker compose up -d'), 'Clipboard content does not match the code block');
    }
    return { buttonCount: 2, clipboardVerified: copiedText !== null, screenshot: await screenshot('copy-success', buttons.first().locator('xpath=..')) };
  });

  await check('anonymous Like routes to login and preserves return URL', async () => {
    await openIssue();
    const button = page.getByRole('button', { name: 'Log in to like this repository', exact: true });
    const stability = await page.evaluate(async () => {
      let header = document.querySelector('.repo-header');
      let overlay = document.querySelector('.nyankoface-repo-title-overlay');
      let button = document.querySelector('.nyankoface-title-like');
      const replacements = { header: 0, overlay: 0, button: 0 };
      for (let sample = 0; sample < 10; sample += 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        const nextHeader = document.querySelector('.repo-header');
        const nextOverlay = document.querySelector('.nyankoface-repo-title-overlay');
        const nextButton = document.querySelector('.nyankoface-title-like');
        if (header !== nextHeader) replacements.header += 1;
        if (overlay !== nextOverlay) replacements.overlay += 1;
        if (button !== nextButton) replacements.button += 1;
        header = nextHeader;
        overlay = nextOverlay;
        button = nextButton;
      }
      return replacements;
    });
    expect(stability.button === 0, `Like button is being repeatedly replaced in the DOM: ${JSON.stringify(stability)}`);
    await button.click();
    await page.waitForURL(/\/git\/user\/login\?redirect_to=/, { timeout: 10_000 });
    expect(page.url().includes(encodeURIComponent(issuePath)), 'Like login redirect lost the issue return URL');
    return { finalUrl: page.url(), screenshot: await screenshot('like-login') };
  });

  await check('App, Files, and Community tabs navigate correctly', async () => {
    const targets = [
      ['App', '/seraphim-labs/qr-code-generator'],
      ['Files', '/git/seraphim-labs/qr-code-generator/src/branch/main'],
      ['Community 4', '/git/seraphim-labs/qr-code-generator/issues'],
    ];
    const navigations = [];
    for (const [label, target] of targets) {
      await openIssue();
      await page.locator(`a:visible[href="${target}"]`).first().click();
      await page.waitForURL((url) => url.pathname === target, { timeout: 15_000 });
      navigations.push({ label, path: new URL(page.url()).pathname });
    }
    return navigations;
  });

  await check('issue page has no horizontal overflow', async () => {
    await openIssue();
    const widths = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    }));
    expect(widths.scroll - widths.client <= 2, `Horizontal overflow is ${widths.scroll - widths.client}px`);
    return widths;
  });

  results.push({
    id: testCase.id,
    viewport: testCase.viewport,
    passed: checks.every(({ passed }) => passed),
    checks,
  });
  await context.close();
  await browser.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  issuePath,
  passed: results.every(({ passed }) => passed),
  results,
};
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);

const lines = [
  '# Issue interaction audit',
  '',
  `- Base URL: ${baseUrl}`,
  `- Result: ${report.passed ? 'PASS' : 'FAIL'}`,
  '',
];
for (const result of results) {
  lines.push(`## ${result.id}`, '');
  for (const item of result.checks) lines.push(`- ${item.passed ? 'PASS' : 'FAIL'} — ${item.name}`);
  lines.push('');
}
await writeFile(join(outputDir, 'REPORT.md'), `${lines.join('\n')}\n`);

if (!report.passed) process.exitCode = 1;
