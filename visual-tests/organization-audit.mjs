import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.ORGANIZATION_QA_OUTPUT_DIR || join(root, 'artifacts', 'organization'));
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

const channel = (value) => {
  const normalized = value / 255;
  return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
};

const luminance = ([r, g, b]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);
const rgb = (value) => value.match(/[\d.]+/g)?.slice(0, 3).map(Number) || [0, 0, 0];

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
    const response = await page.goto(`${baseUrl}/git/nyankoface`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(700);
    const memberAudit = await page.evaluate(() => {
      const content = document.querySelector('.page-content.organization, .page-content');
      const rect = content?.getBoundingClientRect();
      const declared = Number.parseInt(document.querySelector('.nyankoface-org-hf-sidebar h2 span')?.textContent || '0', 10) || 0;
      const memberLink = document.querySelector('.nyankoface-member-cloud > a');
      const memberLinkStyle = memberLink ? getComputedStyle(memberLink) : null;
      return {
        left: rect ? Math.round(rect.left) : null,
        right: rect ? Math.round(document.documentElement.clientWidth - rect.right) : null,
        placeholders: document.querySelectorAll('.nyankoface-member-cloud > span').length,
        avatars: document.querySelectorAll('.nyankoface-member-cloud > img, .nyankoface-member-cloud > a > img').length,
        declared,
        memberLink: memberLinkStyle ? {
          background: memberLinkStyle.backgroundColor,
          borderWidth: memberLinkStyle.borderWidth,
          borderRadius: memberLinkStyle.borderRadius,
          textDecoration: memberLinkStyle.textDecorationLine,
        } : null,
      };
    });
    await page.screenshot({ path: join(outputDir, `${viewport.id}--organization-top.png`) });

    const repoLink = page.locator('.nyankoface-org-repo-card a').first();
    await repoLink.focus();
    await repoLink.scrollIntoViewIfNeeded();
    const focusAudit = await repoLink.evaluate((link) => {
      const card = link.closest('.nyankoface-org-repo-card');
      const linkStyle = getComputedStyle(link);
      const cardStyle = getComputedStyle(card);
      return { foreground: linkStyle.color, background: cardStyle.backgroundColor };
    });
    await page.screenshot({ path: join(outputDir, `${viewport.id}--repository-focus.png`) });

    const defects = [];
    if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
    if (
      viewport.id === 'mobile'
      && (
        memberAudit.left < 16
        || memberAudit.left > 32
        || memberAudit.right < 16
        || memberAudit.right > 32
        || Math.abs(memberAudit.left - memberAudit.right) > 1
      )
    ) {
      defects.push(`mobile side gutters are unbalanced or outside 16-32px: ${memberAudit.left}px/${memberAudit.right}px`);
    }
    if (memberAudit.placeholders !== 0) defects.push(`${memberAudit.placeholders} fake member placeholders`);
    if (memberAudit.avatars !== memberAudit.declared) defects.push(`${memberAudit.declared} declared members but ${memberAudit.avatars} avatars`);
    if (memberAudit.memberLink?.borderWidth !== '0px' || memberAudit.memberLink?.background !== 'rgba(0, 0, 0, 0)') {
      defects.push('member name is rendered as a bordered or filled pill');
    }
    const focusContrast = contrast(rgb(focusAudit.foreground), rgb(focusAudit.background));
    if (focusContrast < 4.5) defects.push(`focused repository contrast is ${focusContrast.toFixed(2)}:1`);

    results.push({ viewport, memberAudit, focusAudit: { ...focusAudit, contrast: Number(focusContrast.toFixed(2)) }, defects });
    process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${viewport.id} organization layout and focus state\n`);
    await context.close();
  }
} finally {
  await browser.close();
}

await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(results, null, 2)}\n`);
if (results.some(({ defects }) => defects.length)) process.exitCode = 1;
