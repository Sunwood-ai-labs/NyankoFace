import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(process.env.ORGANIZATION_EDIT_QA_OUTPUT_DIR || join(root, 'artifacts', 'organization-edit'));
const organizations = [
  { slug: 'nyankoface', fullName: 'NyankoFace' },
  { slug: 'seraphim-labs', fullName: 'Seraphim Labs' },
];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
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
      colorScheme: 'dark',
      reducedMotion: 'reduce',
    });
    await context.addInitScript(() => {
      localStorage.setItem('nyankoface-theme-v2', 'cyberpunk');
      localStorage.setItem('nyankoface-theme', 'cyberpunk');
      document.cookie = 'nyankoface-theme=cyberpunk; Path=/; Max-Age=31536000; SameSite=Lax';
    });
    const page = await context.newPage();
    await page.goto(`${baseUrl}/git/user/login`, { waitUntil: 'domcontentloaded' });
    await page.locator('input[name="user_name"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await Promise.all([
      page.waitForLoadState('domcontentloaded'),
      page.getByRole('button', { name: /log in|login/i }).click(),
    ]);

    for (const organization of organizations) {
      const response = await page.goto(`${baseUrl}/git/org/${organization.slug}/settings`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(450);
      const audit = await page.evaluate(() => {
        const fullName = document.querySelector('input[name="full_name"]');
        const description = document.querySelector('textarea[name="description"]');
        const avatar = document.querySelector('.page-content.organization img.org-avatar');
        const pageStyle = getComputedStyle(document.querySelector('.page-content'));
        const inputStyle = fullName ? getComputedStyle(fullName) : null;
        return {
          fullName: fullName?.value || null,
          description: description?.value || null,
          avatarSrc: avatar?.getAttribute('src') || null,
          pageBackground: pageStyle.backgroundColor,
          inputBackground: inputStyle?.backgroundColor || null,
          inputColor: inputStyle?.color || null,
          horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
          updateButtons: Array.from(document.querySelectorAll('button')).filter((button) => button.textContent.trim() === 'Update settings').length,
        };
      });
      const defects = [];
      if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
      if (audit.fullName !== organization.fullName) defects.push(`full name is ${audit.fullName || 'missing'}`);
      if (!audit.description) defects.push('description is not editable');
      if (!audit.avatarSrc?.includes('/avatars/')) defects.push('organization avatar is missing');
      if (audit.updateButtons !== 1) defects.push(`expected one update button, found ${audit.updateButtons}`);
      if (audit.horizontalOverflow > 2) defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);
      if (audit.pageBackground === 'rgb(255, 255, 255)') defects.push('cyberpunk settings page has a white root surface');
      const screenshot = `${viewport.id}--${organization.slug}--settings.png`;
      await page.screenshot({ path: join(outputDir, screenshot), fullPage: true });
      results.push({ viewport, organization, audit, defects, screenshot });
      process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${viewport.id.padEnd(7)} ${organization.slug} owner settings\n`);
    }
    await context.close();
  }
} finally {
  await browser.close();
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`);
if (passed !== results.length) process.exitCode = 1;
