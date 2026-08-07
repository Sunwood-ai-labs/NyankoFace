import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.PAGES_DEPLOY_QA_OUTPUT_DIR
    || join('..', 'docs', 'evidence', 'issues', '73'),
);
const screenshotDir = join(outputDir, 'screenshots');
const cases = [
  {
    id: 'desktop',
    viewport: { width: 1440, height: 1000 },
    repo: 'pages-deploy-e2e',
    method: 'docs',
  },
  {
    id: 'mobile',
    viewport: { width: 390, height: 844 },
    repo: 'pages-deploy-mobile-e2e',
    method: 'gh-pages',
  },
];

await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function login(viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
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
  assert(!page.url().includes('/user/login'), 'Forgejo login did not complete');
  const storageState = await context.storageState();
  await context.close();
  return storageState;
}

async function layoutAudit(page) {
  return page.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
    horizontalOverflow: Math.max(
      0,
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
    deployHeadingVisible: Boolean(
      document.querySelector('[data-pages-deploy-page] h1')?.getBoundingClientRect().height,
    ),
    formVisible: Boolean(
      document.querySelector('[data-pages-deploy-page] form')?.getBoundingClientRect().height,
    ),
  }));
}

try {
  const anonymousContext = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: cases[0].viewport,
  });
  const anonymousResponse = await anonymousContext.request.post(
    `${baseUrl}/api/pages/nyankoface/pages-deploy-e2e/deploy`,
    { data: { method: 'docs', confirmed: true } },
  );
  assert(anonymousResponse.status() === 401, `anonymous deploy returned ${anonymousResponse.status()}`);
  results.push({
    id: 'anonymous-deploy',
    passed: true,
    status: anonymousResponse.status(),
    expected: 401,
  });
  await anonymousContext.close();

  for (const testCase of cases) {
    const storageState = await login(testCase.viewport);
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: testCase.viewport,
      reducedMotion: 'reduce',
      storageState,
    });
    const page = await context.newPage();

    const directoryResponse = await page.goto(`${baseUrl}/pages`, { waitUntil: 'networkidle' });
    assert(directoryResponse?.status() === 200, `Pages directory returned ${directoryResponse?.status()}`);
    assert(
      await page.getByRole('heading', { name: /静的サイト一覧|Static site directory/i }).isVisible(),
      'Pages directory heading is not visible',
    );
    const directoryScreenshot = `${testCase.id}--pages-directory.png`;
    await page.screenshot({
      path: join(screenshotDir, directoryScreenshot),
      fullPage: false,
    });

    const deployUrl = `${baseUrl}/pages/deploy?owner=nyankoface&repo=${testCase.repo}`;
    const deployResponse = await page.goto(deployUrl, { waitUntil: 'networkidle' });
    assert(deployResponse?.status() === 200, `Pages deploy returned ${deployResponse?.status()}`);
    await page.getByText(`nyankoface/${testCase.repo}`, { exact: true }).waitFor();

    const selectedMethod = page.locator(`input[name="pages-method"][value="${testCase.method}"]`);
    await selectedMethod.check();
    assert(await selectedMethod.isChecked(), `${testCase.method} method was not selected`);
    await page.waitForTimeout(350);

    const confirmation = page.locator('input[type="checkbox"]');
    await confirmation.check();
    assert(await confirmation.isChecked(), 'confirmation checkbox was not checked');

    const before = await layoutAudit(page);
    assert(before.horizontalOverflow <= 2, `pre-deploy overflow is ${before.horizontalOverflow}px`);
    assert(before.deployHeadingVisible, 'deploy heading is clipped');
    assert(before.formVisible, 'deploy form is clipped');
    const formScreenshot = `${testCase.id}--deploy-confirmed.png`;
    await page.screenshot({
      path: join(screenshotDir, formScreenshot),
      fullPage: false,
    });

    await page.getByRole('button', { name: /Pagesをデプロイ|Deploy Pages/i }).click();
    const result = page.locator('[data-pages-deploy-result]');
    await result.waitFor({ state: 'visible', timeout: 30_000 });
    const resultStatus = await result.getAttribute('data-pages-deploy-result');
    assert(resultStatus === 'published', `deploy status is ${resultStatus}`);
    assert(await result.getByText('Commit SHA', { exact: true }).isVisible(), 'commit SHA is missing');
    assert(
      await result.getByRole('link', { name: /サイトを見る|Visit site/i }).isVisible(),
      'published-site link is missing',
    );

    await page.addStyleTag({
      content: 'header.sticky { position: static !important; }',
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(100);
    const resultScreenshot = `${testCase.id}--deploy-result.png`;
    await page.screenshot({
      path: join(screenshotDir, resultScreenshot),
      fullPage: true,
    });
    const after = await layoutAudit(page);
    assert(after.horizontalOverflow <= 2, `post-deploy overflow is ${after.horizontalOverflow}px`);

    const publicResponse = await context.request.get(
      `${baseUrl}/pages/nyankoface/${testCase.repo}/`,
    );
    assert(publicResponse.status() === 200, `published site returned ${publicResponse.status()}`);
    const publicHtml = await publicResponse.text();
    assert(publicHtml.includes('NyankoFace Pages'), 'published HTML is missing the starter title');

    const publicPage = await context.newPage();
    await publicPage.goto(`${baseUrl}/pages/nyankoface/${testCase.repo}/`, {
      waitUntil: 'networkidle',
    });
    const publicScreenshot = `${testCase.id}--published-site.png`;
    await publicPage.screenshot({
      path: join(screenshotDir, publicScreenshot),
      fullPage: false,
    });

    results.push({
      id: testCase.id,
      passed: true,
      viewport: testCase.viewport,
      repo: testCase.repo,
      method: testCase.method,
      resultStatus,
      before,
      after,
      screenshots: {
        directory: directoryScreenshot,
        confirmed: formScreenshot,
        result: resultScreenshot,
        published: publicScreenshot,
      },
    });
    process.stdout.write(`PASS ${testCase.id} ${testCase.method} deploy\n`);
    await context.close();
  }

  const missingContext = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: cases[1].viewport,
  });
  const missingPage = await missingContext.newPage();
  await missingPage.goto(
    `${baseUrl}/pages/deploy?owner=nyankoface&repo=pages-does-not-exist`,
    { waitUntil: 'networkidle' },
  );
  const missingAlert = missingPage.locator('section[role="alert"]');
  await missingAlert.waitFor({ state: 'visible' });
  const missingText = await missingAlert.innerText();
  assert(/not found|unavailable/i.test(missingText), `unexpected missing-repo error: ${missingText}`);
  await missingAlert.scrollIntoViewIfNeeded();
  await missingPage.screenshot({
    path: join(screenshotDir, 'mobile--missing-repository.png'),
    fullPage: false,
  });
  results.push({
    id: 'missing-repository',
    passed: true,
    message: missingText,
    screenshot: 'mobile--missing-repository.png',
  });
  await missingContext.close();
} finally {
  await browser.close();
}

await writeFile(
  join(outputDir, 'pages-deploy-audit.json'),
  `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    baseUrl,
    results,
  }, null, 2)}\n`,
  'utf8',
);

process.stdout.write(`PASS ${results.length} Pages deployment checks\n`);
