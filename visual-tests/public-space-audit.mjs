import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, request } from 'playwright';

const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const owner = process.env.PUBLIC_SPACE_OWNER || 'seraphim-labs';
const repo = process.env.PUBLIC_SPACE_REPO || 'sample-environment-secrets';
const repositoryRoot = path.resolve(import.meta.dirname, '..');
const configuredOutputDir = process.env.PUBLIC_SPACE_QA_OUTPUT_DIR
  || 'visual-tests/artifacts/public-space';
const outputDir = path.isAbsolute(configuredOutputDir)
  ? configuredOutputDir
  : path.resolve(repositoryRoot, configuredOutputDir);
const spacePath = `/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
const startPath = `/api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/start`;
const statusPath = `/runner-api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/status`;
const runPath = `/run/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/`;

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const api = await request.newContext({
  baseURL: baseUrl,
  ignoreHTTPSErrors: true,
});

const startResponse = await api.post(startPath);
const startBody = await startResponse.text();
if (!startResponse.ok()) {
  throw new Error(`Anonymous public Space start failed (${startResponse.status()}): ${startBody}`);
}

let runtimeStatus = null;
for (let attempt = 0; attempt < 90; attempt += 1) {
  const response = await api.get(statusPath);
  if (response.ok()) {
    runtimeStatus = await response.json();
    if (runtimeStatus.status === 'running') break;
  }
  await new Promise((resolve) => setTimeout(resolve, 2_000));
}
if (runtimeStatus?.status !== 'running') {
  throw new Error(`Public Space did not reach running state: ${JSON.stringify(runtimeStatus)}`);
}

const viewports = [
  { name: 'desktop', width: 1440, height: 1000, isMobile: false },
  { name: 'mobile', width: 390, height: 844, isMobile: true },
];
const results = [];

for (const viewport of viewports) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  const response = await page.goto(`${baseUrl}${spacePath}`, { waitUntil: 'networkidle' });
  if (!response?.ok()) {
    throw new Error(`${viewport.name} Space page failed with HTTP ${response?.status()}`);
  }

  const authState = await page.locator('[data-auth-state]').first().getAttribute('data-auth-state');
  if (authState !== 'anonymous') {
    throw new Error(`${viewport.name} did not exercise the anonymous session (state=${authState})`);
  }

  await page.locator('[data-iframe-phase="ready"]').waitFor({ state: 'attached', timeout: 30_000 });
  const iframe = page.locator(`iframe[src^="${runPath}"]`);
  await iframe.waitFor({ state: 'visible', timeout: 30_000 });
  const frame = page.frame({ url: (url) => url.pathname === runPath });
  if (!frame) {
    throw new Error(`${viewport.name} did not load the public Space iframe`);
  }
  await frame.locator('body').waitFor({ state: 'visible', timeout: 30_000 });
  const appText = (await frame.locator('body').innerText()).trim();
  if (!appText) {
    throw new Error(`${viewport.name} loaded an empty Space application`);
  }

  const loginError = page.getByText(/Forgejoにログインして|Sign in to Forgejo/i);
  if (await loginError.count()) {
    throw new Error(`${viewport.name} still renders a Forgejo sign-in error`);
  }

  const metrics = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    bodyWidth: document.body.scrollWidth,
    iframeSrc: document.querySelector('iframe')?.getAttribute('src') || null,
    runtimePhase: document.querySelector('[data-runtime-phase]')?.getAttribute('data-runtime-phase') || null,
    runtimeRequestMs: document.querySelector('[data-runtime-request-ms]')?.getAttribute('data-runtime-request-ms') || null,
    iframePhase: document.querySelector('[data-iframe-phase]')?.getAttribute('data-iframe-phase') || null,
    iframeDurationMs: document.querySelector('[data-iframe-duration-ms]')?.getAttribute('data-iframe-duration-ms') || null,
  }));
  if (metrics.bodyWidth > metrics.viewportWidth + 1) {
    throw new Error(`${viewport.name} has horizontal overflow: ${JSON.stringify(metrics)}`);
  }

  const screenshot = path.join(outputDir, `${viewport.name}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });
  results.push({
    viewport: viewport.name,
    authState,
    appText: appText.slice(0, 160),
    screenshot: path.relative(repositoryRoot, screenshot).replaceAll('\\', '/'),
    ...metrics,
  });
  await context.close();
}

const report = {
  baseUrl,
  owner,
  repo,
  startStatus: startResponse.status(),
  startBody: JSON.parse(startBody),
  runtimeStatus,
  results,
};
await fs.writeFile(
  path.join(outputDir, 'report.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf8',
);

await api.dispose();
await browser.close();
console.log(JSON.stringify(report, null, 2));
