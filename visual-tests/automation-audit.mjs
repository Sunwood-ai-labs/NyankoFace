import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, request } from 'playwright';

const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const owner = process.env.AUTOMATION_QA_OWNER || 'seraphim-labs';
const repo = process.env.AUTOMATION_QA_REPO || 'weekly-repository-report';
const immutableRef = process.env.AUTOMATION_QA_REF || 'v1.0.0';
const repositoryRoot = path.resolve(import.meta.dirname, '..');
const configuredOutputDir = process.env.AUTOMATION_QA_OUTPUT_DIR
  || 'visual-tests/artifacts/automation';
const outputDir = path.isAbsolute(configuredOutputDir)
  ? configuredOutputDir
  : path.resolve(repositoryRoot, configuredOutputDir);
const listPath = '/automations';
const detailPath = `/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
const preflightPath = `/api/automations/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/preflight`;
const bundlePath = `/api/automations/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/bundle`;

const themes = [
  { id: 'standard', colorScheme: 'light' },
  { id: 'solarpunk', colorScheme: 'light' },
  { id: 'cyberpunk', colorScheme: 'dark' },
];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000, isMobile: false },
  { id: 'mobile', width: 390, height: 844, isMobile: true },
];

await fs.rm(outputDir, { recursive: true, force: true });
await fs.mkdir(outputDir, { recursive: true });

const api = await request.newContext({
  baseURL: baseUrl,
  ignoreHTTPSErrors: true,
});

const preflightResponse = await api.get(`${preflightPath}?ref=${encodeURIComponent(immutableRef)}`);
if (!preflightResponse.ok()) {
  throw new Error(`Automation preflight failed (${preflightResponse.status()}): ${await preflightResponse.text()}`);
}
const preflight = await preflightResponse.json();
if (
  preflight.ok !== true
  || preflight.compatible !== true
  || preflight.importState !== 'disabled'
  || preflight.config?.enabled !== false
  || !/^[a-f0-9]{40,64}$/i.test(preflight.source?.sha || '')
  || preflight.findings?.length
) {
  throw new Error(`Automation preflight invariant failed: ${JSON.stringify(preflight)}`);
}

const bundleResponse = await api.post(bundlePath, {
  data: {
    revision: preflight.source.sha,
    acknowledgeWarnings: false,
  },
});
const bundleText = await bundleResponse.text();
if (
  !bundleResponse.ok()
  || !bundleResponse.headers()['content-type']?.startsWith('application/toml')
  || !/\benabled\s*=\s*false\b/.test(bundleText)
  || /\benabled\s*=\s*true\b/.test(bundleText)
) {
  throw new Error(`Unsafe or invalid Automation bundle (${bundleResponse.status()}): ${bundleText}`);
}

const missingResponse = await api.get('/api/automations/nyankoface/definitely-missing/preflight');
if (missingResponse.status() !== 404) {
  throw new Error(`Missing Automation was not hidden with 404 (status=${missingResponse.status()})`);
}
const mutableBundleResponse = await api.post(bundlePath, {
  data: { revision: 'main', acknowledgeWarnings: false },
});
if (mutableBundleResponse.status() !== 400) {
  throw new Error(`Mutable Automation revision was not rejected (status=${mutableBundleResponse.status()})`);
}

const browser = await chromium.launch({ headless: true });
const results = [];
let interactions = null;

try {
  for (const theme of themes) {
    for (const viewport of viewports) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        isMobile: viewport.isMobile,
        hasTouch: viewport.isMobile,
        colorScheme: theme.colorScheme,
        reducedMotion: 'reduce',
        ignoreHTTPSErrors: true,
        permissions: ['clipboard-read', 'clipboard-write'],
      });
      await context.addInitScript((themeId) => {
        localStorage.setItem('nyankoface-theme-v2', themeId);
        localStorage.setItem('nyankoface-theme', themeId);
        document.cookie = `nyankoface-theme=${themeId}; Path=/; Max-Age=31536000; SameSite=Lax`;
      }, theme.id);

      const page = await context.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('pageerror', (error) => pageErrors.push(error.message));

      const listResponse = await page.goto(`${baseUrl}${listPath}`, { waitUntil: 'networkidle' });
      if (!listResponse?.ok()) throw new Error(`${theme.id}/${viewport.id} Automation list HTTP ${listResponse?.status()}`);
      const listLink = page.locator(`a[href="${detailPath}"]`).first();
      await listLink.waitFor({ state: 'visible' });
      const listCard = listLink.locator('xpath=ancestor::article[1]');
      if (await listCard.locator('[data-icon="clock-rotate-left"]').count() !== 1) {
        throw new Error(`${theme.id}/${viewport.id} did not render the Automation card treatment`);
      }
      const listMetrics = await page.evaluate(() => ({
        viewportWidth: window.innerWidth,
        bodyWidth: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth),
        theme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
      }));
      if (listMetrics.bodyWidth > listMetrics.viewportWidth + 1) {
        throw new Error(`${theme.id}/${viewport.id} list overflow: ${JSON.stringify(listMetrics)}`);
      }
      const listScreenshot = path.join(outputDir, `${theme.id}-${viewport.id}-list.png`);
      await page.screenshot({ path: listScreenshot, fullPage: true });

      await listLink.click();
      await page.waitForURL((url) => url.pathname === detailPath);
      await page.waitForLoadState('networkidle');
      const panel = page.locator('[data-automation-preflight]');
      await panel.waitFor({ state: 'visible' });
      const panelText = (await panel.innerText()).replace(/\s+/g, ' ');
      const normalizedPanelText = panelText.toLowerCase();
      for (const expected of [
        'Automation preflight',
        'disabled',
        'Commit SHA',
        'SHA-256',
      ]) {
        if (!normalizedPanelText.includes(expected.toLowerCase())) {
          throw new Error(`${theme.id}/${viewport.id} Automation panel is missing "${expected}"`);
        }
      }
      if (!/閲覧だけでは登録・実行されません|Browsing never registers or runs/.test(panelText)) {
        throw new Error(`${theme.id}/${viewport.id} is missing the no-execution guarantee`);
      }

      const detailMetrics = await page.evaluate(() => ({
        viewportWidth: window.innerWidth,
        bodyWidth: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth),
        theme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
      }));
      if (detailMetrics.bodyWidth > detailMetrics.viewportWidth + 1) {
        throw new Error(`${theme.id}/${viewport.id} detail overflow: ${JSON.stringify(detailMetrics)}`);
      }

      if (!interactions && theme.id === 'standard' && viewport.id === 'desktop') {
        const copyButton = page.getByRole('button', { name: /無効TOMLをコピー|Copy disabled TOML/ });
        await copyButton.click();
        await page.getByRole('status').filter({ hasText: /コピーしました|Copied the disabled TOML/ }).waitFor();
        const clipboard = await page.evaluate(() => navigator.clipboard.readText());
        if (!/\benabled\s*=\s*false\b/.test(clipboard) || /\benabled\s*=\s*true\b/.test(clipboard)) {
          throw new Error('Clipboard export was not the disabled Automation configuration');
        }

        const downloadPromise = page.waitForEvent('download');
        await page.getByRole('button', { name: /安全な設定を取得|Download reviewed config/ }).click();
        const download = await downloadPromise;
        if (download.suggestedFilename() !== `${repo}-automation.toml`) {
          throw new Error(`Unexpected Automation filename: ${download.suggestedFilename()}`);
        }
        const downloadPath = await download.path();
        const downloadedText = await fs.readFile(downloadPath, 'utf8');
        if (!/\benabled\s*=\s*false\b/.test(downloadedText) || /\benabled\s*=\s*true\b/.test(downloadedText)) {
          throw new Error('Downloaded export was not the disabled Automation configuration');
        }
        interactions = {
          listNavigation: true,
          copiedDisabledConfiguration: true,
          downloadedDisabledConfiguration: true,
          suggestedFilename: download.suggestedFilename(),
        };
      }

      const detailScreenshot = path.join(outputDir, `${theme.id}-${viewport.id}-detail.png`);
      await page.screenshot({ path: detailScreenshot, fullPage: true });
      if (consoleErrors.length || pageErrors.length) {
        throw new Error(`${theme.id}/${viewport.id} browser errors: ${JSON.stringify({ consoleErrors, pageErrors })}`);
      }
      results.push({
        theme: theme.id,
        viewport: viewport.id,
        listScreenshot: path.relative(repositoryRoot, listScreenshot).replaceAll('\\', '/'),
        detailScreenshot: path.relative(repositoryRoot, detailScreenshot).replaceAll('\\', '/'),
        listMetrics,
        detailMetrics,
      });
      await context.close();
    }
  }
} finally {
  await browser.close();
  await api.dispose();
}

if (!interactions) throw new Error('Automation interaction audit did not execute');

const report = {
  baseUrl,
  owner,
  repo,
  immutableRef,
  api: {
    preflightStatus: preflightResponse.status(),
    bundleStatus: bundleResponse.status(),
    sourceSha: preflight.source.sha,
    sourceHash: preflight.sourceHash,
    missingRepositoryStatus: missingResponse.status(),
    mutableRevisionStatus: mutableBundleResponse.status(),
    importState: preflight.importState,
  },
  interactions,
  results,
};
await fs.writeFile(path.join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(report, null, 2));
