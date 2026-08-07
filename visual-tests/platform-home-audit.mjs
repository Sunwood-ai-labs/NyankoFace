import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(process.env.PLATFORM_HOME_QA_OUTPUT_DIR || join(root, '..', 'docs', 'evidence', 'issues', '47'));
const includeAuthenticated = process.env.PLATFORM_HOME_AUTH !== 'false';
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];
const themes = ['standard', 'solarpunk', 'cyberpunk'];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

async function loginState(viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: viewport.width, height: viewport.height },
  });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/git/user/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="user_name"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await Promise.all([
    page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: /log in|login/i }).click(),
  ]);
  const state = await context.storageState();
  await context.close();
  return state;
}

async function auditHome(viewport, authenticated, storageState, theme) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: viewport.width, height: viewport.height },
    reducedMotion: 'reduce',
    ...(storageState ? { storageState } : {}),
  });
  const page = await context.newPage();
  await page.addInitScript((selectedTheme) => {
    localStorage.setItem('nyankoface-theme-v2', selectedTheme);
  }, theme);
  const response = await page.goto(`${baseUrl}/`, { waitUntil: 'networkidle' });
  if (authenticated && viewport.id === 'mobile') {
    await page.locator('.nyankoface-mobile-menu-toggle').click();
    await page.waitForTimeout(150);
  }
  const audit = await page.evaluate(() => {
    const bodyText = document.body.textContent?.replace(/\s+/g, ' ') || '';
    const hero = document.querySelector('[data-home-hero="classic"]');
    const profileImage = document.querySelector('[data-auth-state="authenticated"] img');
    return {
      platformMessage:
        bodyText.includes('AIを見つける。試す。作る。公開する。') ||
        bodyText.includes('Find it. Run it. Build it. Publish it.'),
      platformDescription:
        bodyText.includes('AIコンテンツプラットフォーム') ||
        bodyText.includes('AI content platform'),
      classicHero: Boolean(hero),
      heroBackground: hero ? getComputedStyle(hero).backgroundColor : null,
      heroLinks: ['/spaces', '/models'].filter((href) => hero?.querySelector(`a[href="${href}"]`)),
      pagesSection: Boolean(document.querySelector('[data-home-pages-state]')),
      pagesState: document.querySelector('[data-home-pages-state]')?.getAttribute('data-home-pages-state') || null,
      pagesBrowseLinks: document.querySelectorAll('[data-home-pages-state] a[href="/pages"]').length,
      pagesPublishLinks: document.querySelectorAll('[data-home-pages-state] a[href="/pages/deploy"]').length,
      publishedPageLinks: document.querySelectorAll('[data-home-pages-list] a[target="_blank"]').length,
      pagesFallback: Boolean(document.querySelector('.nyankoface-home-pages-fallback')),
      profileAvatarSrc: profileImage?.getAttribute('src') || null,
      profileAvatarLoaded: profileImage ? profileImage.complete && profileImage.naturalWidth > 0 : null,
      anonymousControls: document.querySelectorAll('[data-auth-state="anonymous"]').length,
      authenticatedControls: document.querySelectorAll('[data-auth-state="authenticated"]').length,
      horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    };
  });
  const defects = [];
  if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
  if (!audit.platformMessage) defects.push('platform value proposition is missing');
  if (!audit.platformDescription) defects.push('platform description is missing');
  if (!audit.classicHero) defects.push('classic light hero is missing');
  if (audit.heroLinks.length !== 2) defects.push(`expected classic hero links, found ${audit.heroLinks.length}`);
  if (!audit.pagesSection) defects.push('Pages discovery section is missing');
  if (audit.pagesBrowseLinks < 2) defects.push(`expected two Pages browse links, found ${audit.pagesBrowseLinks}`);
  if (audit.pagesPublishLinks < 1) defects.push('Pages publishing link is missing');
  if (audit.publishedPageLinks < 1 && !audit.pagesFallback) defects.push('Pages preview and fallback are both missing');
  if (authenticated && !audit.profileAvatarSrc?.includes('/git/assets/img/avatars/lina-park.png')) {
    defects.push(`profile avatar is not normalized: ${audit.profileAvatarSrc}`);
  }
  if (authenticated && audit.profileAvatarLoaded === false) defects.push(`profile avatar failed to load: ${audit.profileAvatarSrc}`);
  if (audit.horizontalOverflow > 2) defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);
  const screenshot = `${theme}--${viewport.id}--${authenticated ? 'authenticated' : 'anonymous'}--classic-home.png`;
  await page.screenshot({ path: join(outputDir, screenshot), fullPage: false });
  const pagesScreenshot = `${theme}--${viewport.id}--${authenticated ? 'authenticated' : 'anonymous'}--pages-discovery.png`;
  await page.locator('[data-home-pages-state]').screenshot({ path: join(outputDir, pagesScreenshot) });
  results.push({ theme, viewport, authenticated, audit, defects, screenshot, pagesScreenshot });
  process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${theme.padEnd(9)} ${viewport.id.padEnd(7)} ${authenticated ? 'authenticated' : 'anonymous'} platform home\n`);
  await context.close();
}

try {
  for (const theme of themes) {
    for (const viewport of viewports) {
      await auditHome(viewport, false, null, theme);
      if (includeAuthenticated) await auditHome(viewport, true, await loginState(viewport), theme);
    }
  }
} finally {
  await browser.close();
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`);
if (passed !== results.length) process.exitCode = 1;
