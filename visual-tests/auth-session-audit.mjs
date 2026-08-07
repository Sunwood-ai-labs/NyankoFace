import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(process.env.AUTH_SESSION_QA_OUTPUT_DIR || join(root, '..', 'docs', 'evidence', 'issues', '25'));
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

async function auditAuthenticatedNavigation(page, viewport) {
  for (const path of ['/', '/spaces']) {
    const response = await page.goto(`${baseUrl}${path}`, { waitUntil: 'networkidle' });
    if (viewport.id === 'mobile') {
      await page.locator('.nyankoface-mobile-menu-toggle').click();
    }
    const audit = await page.evaluate(() => {
      const visible = (element) => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      const authenticated = [...document.querySelectorAll('[data-auth-state="authenticated"]')].find(visible);
      const anonymous = [...document.querySelectorAll('[data-auth-state="anonymous"]')].find(visible);
      const profileImage = authenticated?.querySelector('img');
      return {
        authenticatedVisible: Boolean(authenticated),
        anonymousVisible: Boolean(anonymous),
        accountText: authenticated?.textContent?.replace(/\s+/g, ' ').trim() || '',
        avatarSrc: profileImage?.getAttribute('src') || null,
        avatarLoaded: profileImage ? profileImage.complete && profileImage.naturalWidth > 0 : null,
        horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      };
    });
    const defects = [];
    if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
    if (!audit.authenticatedVisible) defects.push('authenticated account is not visible');
    if (audit.anonymousVisible) defects.push('anonymous login controls remain visible');
    if (!audit.accountText.includes(username)) defects.push(`account name is missing: ${audit.accountText}`);
    if (audit.avatarSrc && !audit.avatarSrc.startsWith('/git/')) defects.push(`avatar path bypasses Forgejo mount: ${audit.avatarSrc}`);
    if (audit.avatarLoaded === false) defects.push(`avatar failed to load: ${audit.avatarSrc}`);
    if (audit.horizontalOverflow > 2) defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);
    const screenshot = `${viewport.id}--authenticated--${path === '/' ? 'home' : 'spaces'}.png`;
    await page.screenshot({ path: join(outputDir, screenshot), fullPage: false });
    results.push({ viewport, path, audit, defects, screenshot });
    process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${viewport.id.padEnd(7)} ${path} authenticated session\n`);
  }
}

try {
  for (const viewport of viewports) {
    const loginContext = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      reducedMotion: 'reduce',
    });
    const loginPage = await loginContext.newPage();
    await loginPage.goto(`${baseUrl}/git/user/login`, { waitUntil: 'domcontentloaded' });
    await loginPage.locator('input[name="user_name"]').fill(username);
    await loginPage.locator('input[name="password"]').fill(password);
    await Promise.all([
      loginPage.waitForLoadState('domcontentloaded'),
      loginPage.getByRole('button', { name: /log in|login/i }).click(),
    ]);
    const storageState = await loginContext.storageState();
    await loginContext.close();

    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      reducedMotion: 'reduce',
      storageState,
    });
    const page = await context.newPage();
    await auditAuthenticatedNavigation(page, viewport);
    await page.reload({ waitUntil: 'networkidle' });
    const reloadedState = await page.evaluate(() => ({
      authenticated: document.querySelectorAll('[data-auth-state="authenticated"]').length,
      anonymous: document.querySelectorAll('[data-auth-state="anonymous"]').length,
    }));
    if (reloadedState.authenticated < 1 || reloadedState.anonymous > 0) {
      results.push({
        viewport,
        path: '/spaces reload',
        audit: reloadedState,
        defects: [`authenticated state was not retained after reload: ${JSON.stringify(reloadedState)}`],
      });
    }
    await context.close();

    const noJavaScriptContext = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      javaScriptEnabled: false,
      storageState,
    });
    const noJavaScriptPage = await noJavaScriptContext.newPage();
    await noJavaScriptPage.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded' });
    const serverMarkup = await noJavaScriptPage.locator('body').textContent();
    const serverDefects = [];
    if (!serverMarkup?.includes(username)) serverDefects.push('server-rendered account name is missing');
    if (serverMarkup?.includes('Sign up') || serverMarkup?.includes('新規登録')) serverDefects.push('server-rendered anonymous controls are present');
    results.push({
      viewport,
      path: '/ server markup',
      audit: { accountPresent: serverMarkup?.includes(username) || false },
      defects: serverDefects,
    });
    process.stdout.write(`${serverDefects.length ? 'FAIL' : 'PASS'} ${viewport.id.padEnd(7)} / server-rendered session\n`);
    await noJavaScriptContext.close();
  }
} finally {
  await browser.close();
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`);
if (passed !== results.length) process.exitCode = 1;
