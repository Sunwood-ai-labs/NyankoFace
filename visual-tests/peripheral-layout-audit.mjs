import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.PERIPHERAL_LAYOUT_QA_OUTPUT_DIR || join(root, 'artifacts', 'peripheral-layout'),
);
const routes = [
  {
    id: 'settings',
    path: '/git/user/settings',
    bodyAttribute: 'data-nyankoface-settings',
    contentSelector: '.user-setting-content',
  },
  {
    id: 'notifications',
    path: '/git/notifications/subscriptions',
    bodyAttribute: 'data-nyankoface-notifications',
    contentSelector: '#notification_table, .notification-list, .ui.segment',
  },
  {
    id: 'admin',
    path: '/git/admin',
    bodyAttribute: 'data-nyankoface-admin-page',
    contentSelector: '.admin-setting-content',
  },
];
const viewports = [
  { id: 'desktop-1280', width: 1280, height: 900 },
  { id: 'desktop-1440', width: 1440, height: 1000 },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      colorScheme: 'light',
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

    for (const route of routes) {
      const response = await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(350);
      const audit = await page.evaluate(
        ({ bodyAttribute, contentSelector }) => {
          const box = (element) => {
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
              x: Math.round(rect.x * 10) / 10,
              width: Math.round(rect.width * 10) / 10,
              right: Math.round(rect.right * 10) / 10,
              display: style.display,
              maxWidth: style.maxWidth,
              gridTemplateColumns: style.gridTemplateColumns,
            };
          };
          const pageContent = document.querySelector('.page-content');
          const containers = pageContent
            ? Array.from(pageContent.querySelectorAll(':scope > .ui.container'))
            : [];
          const container = containers.find((element) => element.getBoundingClientRect().width > 0) || null;
          const mainContent = document.querySelector(contentSelector);
          const nav = document.querySelector('#navbar');
          const pageStyle = pageContent ? getComputedStyle(pageContent) : null;
          return {
            viewportWidth: document.documentElement.clientWidth,
            horizontalOverflow: Math.max(
              0,
              document.documentElement.scrollWidth - document.documentElement.clientWidth,
            ),
            hasBodyAttribute: document.body.hasAttribute(bodyAttribute),
            page: box(pageContent),
            container: box(container),
            mainContent: box(mainContent),
            nav: box(nav),
            strayRepositoryLandingCount: document.querySelectorAll(
              '.nyankoface-model-landing, .nyankoface-space-landing, .nyankoface-dataset-landing',
            ).length,
            pagePaddingLeft: pageStyle ? Number.parseFloat(pageStyle.paddingLeft) : null,
            pagePaddingRight: pageStyle ? Number.parseFloat(pageStyle.paddingRight) : null,
          };
        },
        { bodyAttribute: route.bodyAttribute, contentSelector: route.contentSelector },
      );

      const defects = [];
      const expectedPageWidth = Math.min(1280, viewport.width - 64);
      if (!response || response.status() >= 400) defects.push(`HTTP ${response?.status() ?? 'none'}`);
      if (!audit.hasBodyAttribute) defects.push(`missing ${route.bodyAttribute}`);
      if (!audit.page) defects.push('page-content is missing');
      if (!audit.container) defects.push('primary ui.container is missing');
      if (!audit.mainContent) defects.push(`main content ${route.contentSelector} is missing`);
      if (audit.strayRepositoryLandingCount > 0) {
        defects.push(`found ${audit.strayRepositoryLandingCount} unrelated repository landing`);
      }
      if (audit.horizontalOverflow > 2) defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);
      if (audit.page && Math.abs(audit.page.width - expectedPageWidth) > 2) {
        defects.push(`page width is ${audit.page.width}px; expected ${expectedPageWidth}px`);
      }
      if (audit.page && Math.abs(audit.page.x - (viewport.width - audit.page.width) / 2) > 2) {
        defects.push(`page is not centered (x=${audit.page.x}px)`);
      }
      const pageInnerWidth = audit.page
        ? audit.page.width - (audit.pagePaddingLeft || 0) - (audit.pagePaddingRight || 0)
        : 0;
      const expectedContainerX =
        audit.page && audit.container
          ? audit.page.x + (audit.pagePaddingLeft || 0) + (pageInnerWidth - audit.container.width) / 2
          : 0;
      if (audit.container && audit.page && Math.abs(audit.container.x - expectedContainerX) > 2) {
        defects.push(`container left edge is misaligned (x=${audit.container.x}px)`);
      }
      if (Math.abs((audit.pagePaddingLeft || 0) - 32) > 1 || Math.abs((audit.pagePaddingRight || 0) - 32) > 1) {
        defects.push(
          `desktop page gutter is ${audit.pagePaddingLeft}px/${audit.pagePaddingRight}px; expected 32px`,
        );
      }
      if (route.id === 'settings' && audit.container && (audit.container.width < 900 || audit.container.width > 982)) {
        defects.push(`settings container width is ${audit.container.width}px; expected 900-982px`);
      }
      if (
        route.id !== 'settings' &&
        audit.container &&
        audit.container.width < Math.min(1100, expectedPageWidth - 64)
      ) {
        defects.push(`${route.id} container is too narrow at ${audit.container.width}px`);
      }
      if (audit.mainContent && audit.mainContent.width < 600) {
        defects.push(`main content is too narrow at ${audit.mainContent.width}px`);
      }

      const screenshot = `${viewport.id}--${route.id}.png`;
      await page.screenshot({ path: join(outputDir, screenshot), fullPage: true });
      results.push({ viewport, route, audit, defects, screenshot });
      process.stdout.write(`${defects.length ? 'FAIL' : 'PASS'} ${viewport.id.padEnd(12)} ${route.id}\n`);
    }
    await context.close();
  }
} finally {
  await browser.close();
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(
  join(outputDir, 'report.json'),
  `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`,
);
if (passed !== results.length) process.exitCode = 1;
