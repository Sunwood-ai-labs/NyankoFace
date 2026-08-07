import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const baseUrl = (
  process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443'
).replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.PIPELINE_QA_OUTPUT_DIR
    || join('..', 'docs', 'evidence', 'issues', '70', 'theme-matrix'),
);
const screenshotDir = join(outputDir, 'screenshots');
const targetUrl = `${baseUrl}/nyankoface/pages-starter?tab=pipelines`;
const themes = [
  { id: 'standard', colorScheme: 'light' },
  { id: 'solarpunk', colorScheme: 'light' },
  { id: 'cyberpunk', colorScheme: 'dark' },
];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function login() {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/git/user/login`, {
    waitUntil: 'domcontentloaded',
  });
  await page.locator('input[name="user_name"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await Promise.all([
    page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: /log in|login/i }).click(),
  ]);
  assert(!page.url().includes('/user/login'), 'Forgejo login did not complete');
  const storageState = await context.storageState();
  await context.close();
  return storageState;
}

async function inspect(page) {
  return page.evaluate(() => {
    const channel = (value) => {
      const normalized = value / 255;
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    };
    const luminance = (color) => {
      const values = color.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [];
      if (values.length !== 3) return null;
      return (
        (0.2126 * channel(values[0]))
        + (0.7152 * channel(values[1]))
        + (0.0722 * channel(values[2]))
      );
    };
    const contrast = (foreground, background) => {
      const first = luminance(foreground);
      const second = luminance(background);
      if (first === null || second === null) return null;
      return (Math.max(first, second) + 0.05)
        / (Math.min(first, second) + 0.05);
    };
    const panel = document.querySelector('[data-pipeline-panel]');
    const runner = panel?.querySelector('[data-pipeline-runner]');
    const optionValues = runner
      ? Array.from(runner.querySelectorAll('option')).map((option) => option.value)
      : [];
    const runnerOptions = runner
      ? Array.from(runner.querySelectorAll('option')).map((option) => ({
        value: option.value,
        label: option.textContent?.trim() || '',
        disabled: option.disabled,
      }))
      : [];
    const buttons = Array.from(
      panel?.querySelectorAll('button, a[href]') || [],
    ).filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && rect.width > 0 && rect.height > 0;
    });
    const shortControls = buttons
      .map((element) => ({
        text: element.textContent?.replace(/\s+/g, ' ').trim() || '',
        height: Math.round(element.getBoundingClientRect().height),
      }))
      .filter(({ height }) => height < 40);
    return {
      theme: document.documentElement.getAttribute('data-nyankoface-theme')
        || 'standard',
      overflow: Math.max(
        0,
        document.documentElement.scrollWidth
          - document.documentElement.clientWidth,
      ),
      panelVisible: Boolean(panel?.getBoundingClientRect().height),
      dispatchVisible: Boolean(
        panel?.querySelector('[data-pipeline-dispatch]')
          ?.getBoundingClientRect().height,
      ),
      runCount: panel?.querySelectorAll('[data-pipeline-run]').length || 0,
      runnerOptions: optionValues,
      runnerOptionStates: runnerOptions,
      openJobs: Array.from(
        panel?.querySelectorAll('[data-pipeline-detail] details') || [],
      ).map((details) => details.open),
      wrapPressed: panel
        ?.querySelector('[data-pipeline-detail] button[aria-pressed]')
        ?.getAttribute('aria-pressed') || null,
      logWhiteSpace: (() => {
        const pre = panel?.querySelector('[data-pipeline-detail] pre');
        return pre ? getComputedStyle(pre).whiteSpace : null;
      })(),
      stepContrast: Array.from(
        panel?.querySelectorAll('.nyankoface-pipeline-step-chip') || [],
      ).map((chip) => {
        const style = getComputedStyle(chip);
        return contrast(style.color, style.backgroundColor);
      }),
      shortControls,
    };
  });
}

try {
  const storageState = await login();

  for (const theme of themes) {
    for (const viewport of viewports) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: theme.colorScheme,
        reducedMotion: 'reduce',
        storageState,
      });
      const page = await context.newPage();
      await page.addInitScript((themeId) => {
        localStorage.setItem('nyankoface-theme-v2', themeId);
        document.cookie = `nyankoface-theme=${themeId}; Path=/; Max-Age=31536000; SameSite=Lax`;
      }, theme.id);

      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('pageerror', (error) => pageErrors.push(error.message));

      const response = await page.goto(targetUrl, {
        waitUntil: 'domcontentloaded',
        timeout: 45_000,
      });
      assert(response?.status() === 200, `${theme.id}/${viewport.id}: HTTP ${response?.status()}`);
      await page.locator('[data-pipeline-panel]').waitFor({
        state: 'visible',
        timeout: 30_000,
      });
      await page.waitForTimeout(500);

      const historyState = await inspect(page);
      assert(historyState.theme === theme.id, `${theme.id}/${viewport.id}: theme is ${historyState.theme}`);
      assert(historyState.overflow <= 2, `${theme.id}/${viewport.id}: ${historyState.overflow}px horizontal overflow`);
      assert(historyState.panelVisible, `${theme.id}/${viewport.id}: panel is hidden`);
      assert(historyState.dispatchVisible, `${theme.id}/${viewport.id}: dispatch controls are hidden`);
      assert(
        historyState.runnerOptions.includes('node20')
          && historyState.runnerOptions.includes('gpu'),
        `${theme.id}/${viewport.id}: CPU/GPU runner options are missing`,
      );
      const cpuRunner = historyState.runnerOptionStates.find(
        ({ value }) => value === 'node20',
      );
      const gpuRunner = historyState.runnerOptionStates.find(
        ({ value }) => value === 'gpu',
      );
      assert(
        cpuRunner && !cpuRunner.disabled && /online|オンライン/i.test(cpuRunner.label),
        `${theme.id}/${viewport.id}: CPU runner is not reported online`,
      );
      assert(
        gpuRunner?.disabled && /unavailable|利用不可/i.test(gpuRunner.label),
        `${theme.id}/${viewport.id}: unavailable GPU runner remains selectable`,
      );
      assert(
        historyState.shortControls.length === 0,
        `${theme.id}/${viewport.id}: undersized controls ${JSON.stringify(historyState.shortControls)}`,
      );
      const environmentRun = page
        .locator('[data-pipeline-run]')
        .filter({ hasText: /環境URL準備済み|Environment ready/i })
        .first();
      assert(
        await environmentRun.count(),
        `${theme.id}/${viewport.id}: no published staging or preview environment link`,
      );

      const historyScreenshot = `${theme.id}--${viewport.id}--history.png`;
      await page.screenshot({
        path: join(screenshotDir, historyScreenshot),
        fullPage: false,
      });

      let detailScreenshot = null;
      let logScreenshot = null;
      let detailMetrics = null;
      let logMetrics = null;
      if (historyState.runCount > 0) {
        const successfulRun = page
          .locator('[data-pipeline-run]')
          .filter({ hasText: /success|成功/i })
          .first();
        const runToInspect = await environmentRun.count()
          ? environmentRun
          : await successfulRun.count()
            ? successfulRun
            : page.locator('[data-pipeline-run]').first();
        const scrollBeforeSelection = await page.evaluate(() => window.scrollY);
        await runToInspect.click();
        const detail = page.locator('[data-pipeline-detail]');
        await detail.waitFor({ state: 'visible', timeout: 30_000 });
        await detail.locator('details').first().waitFor({
          state: 'visible',
          timeout: 30_000,
        });
        await detail.scrollIntoViewIfNeeded();
        await page.waitForTimeout(500);
        const detailState = await inspect(page);
        detailMetrics = detailState;
        assert(detailState.overflow <= 2, `${theme.id}/${viewport.id}: detail overflow ${detailState.overflow}px`);
        assert(
          detailState.openJobs.length > 0,
          `${theme.id}/${viewport.id}: selected run has no job disclosures`,
        );
        assert(
          detailState.openJobs.every((open) => !open),
          `${theme.id}/${viewport.id}: successful jobs should start collapsed`,
        );
        const openEnvironment = detail.locator(
          'a[href*="/staging/"], a[href*="/previews/"]',
        );
        assert(
          await openEnvironment.count(),
          `${theme.id}/${viewport.id}: published environment link is missing from run details`,
        );
        if (viewport.id === 'mobile') {
          const scrollAfterSelection = await page.evaluate(() => window.scrollY);
          assert(
            scrollAfterSelection > scrollBeforeSelection,
            `${theme.id}/${viewport.id}: selecting a run did not move focus to details`,
          );
        }
        detailScreenshot = `${theme.id}--${viewport.id}--detail.png`;
        await page.screenshot({
          path: join(screenshotDir, detailScreenshot),
          fullPage: false,
        });

        const firstJob = detail.locator('details').first();
        await firstJob.locator('summary').click();
        await page
          .getByRole('button', { name: /ログ折返し: ON|Log wrap: on/i })
          .click();
        await page.waitForTimeout(150);
        const logState = await inspect(page);
        logMetrics = logState;
        assert(
          logState.openJobs[0] === true,
          `${theme.id}/${viewport.id}: job disclosure did not open`,
        );
        assert(
          logState.wrapPressed === 'false' && logState.logWhiteSpace === 'pre',
          `${theme.id}/${viewport.id}: log wrap toggle did not expose horizontal scrolling`,
        );
        assert(
          logState.stepContrast.length > 0
            && logState.stepContrast.every((ratio) => ratio !== null && ratio >= 4.5),
          `${theme.id}/${viewport.id}: step chip contrast ${JSON.stringify(logState.stepContrast)}`,
        );
        logScreenshot = `${theme.id}--${viewport.id}--job-log.png`;
        await page.screenshot({
          path: join(screenshotDir, logScreenshot),
          fullPage: false,
        });
      }

      assert(consoleErrors.length === 0, `${theme.id}/${viewport.id}: console errors ${consoleErrors.join(' | ')}`);
      assert(pageErrors.length === 0, `${theme.id}/${viewport.id}: page errors ${pageErrors.join(' | ')}`);
      results.push({
        theme: theme.id,
        viewport: viewport.id,
        history: historyState,
        detail: detailMetrics,
        jobLog: logMetrics,
        screenshots: {
          history: historyScreenshot,
          detail: detailScreenshot,
          jobLog: logScreenshot,
        },
      });
      process.stdout.write(
        `PASS ${theme.id.padEnd(10)} ${viewport.id} pipeline UI\n`,
      );
      await context.close();
    }
  }
} finally {
  await browser.close();
}

await writeFile(
  join(outputDir, 'report.json'),
  `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    baseUrl,
    targetUrl,
    results,
  }, null, 2)}\n`,
  'utf8',
);
