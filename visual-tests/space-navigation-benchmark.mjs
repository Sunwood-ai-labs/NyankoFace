import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const candidateUrl = (process.env.CANDIDATE_URL || 'http://localhost:8090').replace(/\/$/, '');
const baselineUrl = process.env.BASELINE_URL?.replace(/\/$/, '') || null;
const samples = Math.max(3, Number.parseInt(process.env.SPACE_NAV_SAMPLES || '10', 10));
const targetPath = process.env.SPACE_NAV_TARGET || '/seraphim-labs/sample-vue';
const reportPath = process.env.SPACE_NAV_REPORT || null;

function percentile(values, percentileValue) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil((percentileValue / 100) * sorted.length) - 1)];
}

function summarize(rows) {
  const durations = rows.map((row) => row.durationMs);
  const feedback = rows.map((row) => row.feedbackMs);
  return {
    samples: rows.length,
    durationMs: { p50: percentile(durations, 50), p95: percentile(durations, 95) },
    feedbackMs: { p50: percentile(feedback, 50), p95: percentile(feedback, 95) },
  };
}

async function measure(browser, label, baseUrl, cacheState) {
  const rows = [];
  const sharedContext = cacheState === 'warm'
    ? await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    : null;

  for (let index = 0; index < samples; index += 1) {
    const context = sharedContext || await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    await page.goto(`${baseUrl}/spaces`, { waitUntil: 'networkidle' });
    const link = page.locator(`a[href="${targetPath}"]`).first();
    await link.waitFor({ state: 'visible', timeout: 30_000 });
    const feedbackKey = `nyankoface:space-navigation-feedback:${cacheState}:${index}:${Date.now()}`;
    await page.evaluate(({ path, key }) => {
      const anchor = document.querySelector(`a[href="${path}"]`);
      if (!anchor) throw new Error(`Space link ${path} was not rendered`);
      sessionStorage.removeItem(key);
      let clickedAt = null;
      const observer = new MutationObserver(() => {
        if (
          clickedAt !== null
          && (anchor.hasAttribute('data-nyankoface-navigation-pending') || anchor.getAttribute('aria-busy') === 'true')
        ) {
          sessionStorage.setItem(key, String(Math.round(performance.now() - clickedAt)));
          observer.disconnect();
        }
      });
      observer.observe(anchor, { attributes: true });
      window.addEventListener('click', (event) => {
        if (event.target instanceof Node && anchor.contains(event.target)) {
          clickedAt = event.timeStamp;
        }
      }, { capture: true, once: true });
    }, { path: targetPath, key: feedbackKey });
    const startedAt = Date.now();
    await link.click({ noWaitAfter: true });
    await page.waitForURL((url) => url.pathname === targetPath, { timeout: 30_000 });
    await page.locator('main h1').filter({ hasText: targetPath.split('/').at(-1) }).waitFor({ state: 'visible', timeout: 30_000 });
    const durationMs = Date.now() - startedAt;
    const feedbackMs = await page.evaluate((key) => {
      const recorded = sessionStorage.getItem(key);
      sessionStorage.removeItem(key);
      return recorded === null ? null : Number.parseInt(recorded, 10);
    }, feedbackKey);
    if (!Number.isFinite(feedbackMs)) {
      throw new Error(`${label} ${cacheState} sample ${index + 1} did not render immediate navigation feedback`);
    }
    rows.push({ index: index + 1, durationMs, feedbackMs });
    await page.close();
    if (!sharedContext) await context.close();
  }

  if (sharedContext) await sharedContext.close();
  return { label, baseUrl, cacheState, rows, summary: summarize(rows) };
}

const browser = await chromium.launch({ headless: true });
const targets = baselineUrl
  ? [{ label: 'baseline', url: baselineUrl }, { label: 'candidate', url: candidateUrl }]
  : [{ label: 'candidate', url: candidateUrl }];
const results = [];

try {
  for (const target of targets) {
    results.push(await measure(browser, target.label, target.url, 'cold'));
    results.push(await measure(browser, target.label, target.url, 'warm'));
  }
} finally {
  await browser.close();
}

const comparison = baselineUrl
  ? Object.fromEntries(['cold', 'warm'].map((cacheState) => {
      const before = results.find((result) => result.label === 'baseline' && result.cacheState === cacheState).summary;
      const after = results.find((result) => result.label === 'candidate' && result.cacheState === cacheState).summary;
      return [cacheState, {
        durationP50DeltaMs: after.durationMs.p50 - before.durationMs.p50,
        durationP95DeltaMs: after.durationMs.p95 - before.durationMs.p95,
        feedbackP95Ms: after.feedbackMs.p95,
      }];
    }))
  : null;
const report = { targetPath, samples, generatedAt: new Date().toISOString(), results, comparison };

if (reportPath) {
  await fs.mkdir(path.dirname(path.resolve(reportPath)), { recursive: true });
  await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
}
console.log(JSON.stringify(report, null, 2));

const feedbackViolations = results
  .filter((result) => result.label === 'candidate' && result.summary.feedbackMs.p95 > 100)
  .map((result) => `${result.cacheState} feedback p95 exceeded 100 ms: ${result.summary.feedbackMs.p95} ms`);
if (feedbackViolations.length > 0) {
  throw new Error(feedbackViolations.join('; '));
}
