import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';

const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.SPACE_ENVIRONMENT_QA_OUTPUT_DIR
    || join('..', 'docs', 'evidence', 'issues', '69'),
);
const screenshotDir = join(outputDir, 'screenshots');
const targetUrl = `${baseUrl}/seraphim-labs/sample-gradio`;
const entryName = 'ISSUE_69_UI_MODE';

await mkdir(screenshotDir, { recursive: true });
const browser = await chromium.launch({ headless: true });

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

async function openDialog(context) {
  const page = await context.newPage();
  await page.goto(targetUrl, { waitUntil: 'networkidle' });
  await page.getByRole('button', {
    name: /VariablesとSecretsを管理|Manage Variables and Secrets/i,
  }).click();
  await page.getByRole('dialog').waitFor();
  return page;
}

function layout(page) {
  return page.evaluate(() => ({
    width: window.innerWidth,
    overflow: Math.max(
      0,
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    ),
    dialogVisible: Boolean(document.querySelector('[role="dialog"]')?.getBoundingClientRect().height),
  }));
}

const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  checks: [],
};

try {
  const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
  const anonymousResponse = await anonymous.request.get(
    `${baseUrl}/runner-api/v1/spaces/seraphim-labs/sample-gradio/environment`,
  );
  assert(anonymousResponse.status() === 401, `anonymous API returned ${anonymousResponse.status()}`);
  report.checks.push({ id: 'anonymous-api', passed: true, status: 401 });
  await anonymous.close();

  const storageState = await login();
  const desktop = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
    storageState,
  });
  const desktopPage = await openDialog(desktop);
  await desktopPage.getByLabel(/種類|Type/i).selectOption('variable');
  await desktopPage.getByLabel(/環境変数名|Environment name/i).fill(entryName);
  await desktopPage.getByLabel(/Variable値|Variable value/i).fill('visual-qa');
  await desktopPage.getByRole('button', { name: /保存／ローテーション|Save \/ rotate/i }).click();
  const row = desktopPage.locator(`[data-space-environment-name="${entryName}"]`);
  await row.waitFor();
  await row.getByRole('button', { name: /無効化|Disable/i }).click();
  await row.getByRole('button', { name: /有効化|Enable/i }).waitFor();
  const desktopLayout = await layout(desktopPage);
  assert(desktopLayout.overflow === 0, `desktop overflow is ${desktopLayout.overflow}px`);
  assert(desktopLayout.dialogVisible, 'desktop dialog is not visible');
  await desktopPage.screenshot({
    path: join(screenshotDir, 'desktop--disabled-setting.png'),
    fullPage: false,
  });
  report.checks.push({
    id: 'desktop-dialog',
    passed: true,
    ...desktopLayout,
    screenshot: 'desktop--disabled-setting.png',
  });

  const mobile = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
    reducedMotion: 'reduce',
    storageState,
  });
  const mobilePage = await openDialog(mobile);
  const mobileRow = mobilePage.locator(`[data-space-environment-name="${entryName}"]`);
  await mobileRow.scrollIntoViewIfNeeded();
  await mobileRow.getByRole('button', { name: /有効化|Enable/i }).waitFor();
  const mobileLayout = await layout(mobilePage);
  assert(mobileLayout.overflow === 0, `mobile overflow is ${mobileLayout.overflow}px`);
  assert(mobileLayout.dialogVisible, 'mobile dialog is not visible');
  await mobilePage.screenshot({
    path: join(screenshotDir, 'mobile--disabled-setting.png'),
    fullPage: false,
  });
  report.checks.push({
    id: 'mobile-dialog',
    passed: true,
    ...mobileLayout,
    screenshot: 'mobile--disabled-setting.png',
  });
  await mobile.close();

  await row.getByRole('button', { name: /削除|Delete/i }).click();
  await row.getByRole('button', { name: /削除を確認|Confirm delete/i }).click();
  await row.waitFor({ state: 'detached' });
  report.checks.push({ id: 'cleanup', passed: true });
  await desktop.close();

  const docs = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
  });
  const docsPage = await docs.newPage();
  const docsResponse = await docsPage.goto(`${baseUrl}/runner-api/docs`, {
    waitUntil: 'networkidle',
  });
  assert(docsResponse?.status() === 200, `OpenAPI docs returned ${docsResponse?.status()}`);
  await docsPage.locator('#swagger-ui').waitFor();
  await docsPage.locator('.opblock-tag').first().waitFor();
  assert(
    await docsPage.locator('.errors-wrapper').count() === 0,
    'OpenAPI docs rendered a Swagger parser error',
  );
  await docsPage.screenshot({
    path: join(screenshotDir, 'desktop--openapi.png'),
    fullPage: false,
  });
  report.checks.push({
    id: 'openapi-docs',
    passed: true,
    status: 200,
    screenshot: 'desktop--openapi.png',
  });
  await docs.close();
} finally {
  await browser.close();
}

await writeFile(
  join(outputDir, 'space-environment-api-audit.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf8',
);
process.stdout.write(`PASS ${report.checks.length} Space environment API checks\n`);
