import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const outputDir = resolve(
  process.env.CONTAINER_WIDTH_QA_OUTPUT_DIR || join(root, 'artifacts', 'container-width'),
);

const affectedRoutes = [
  { id: 'explore-models', path: '/git/explore/repos', auth: false },
  { id: 'explore-datasets', path: '/git/explore/repos?q=dataset', auth: false },
  { id: 'explore-spaces', path: '/git/explore/repos?q=space', auth: false },
  { id: 'not-found', path: '/git/nyankoface/layout-audit-missing', auth: false, expectedStatus: 404 },
  { id: 'repo-create', path: '/git/repo/create', auth: true, narrowForm: true },
  { id: 'org-create', path: '/git/org/create', auth: true, narrowForm: true },
  { id: 'nyankoface-members', path: '/git/org/nyankoface/members', auth: true },
  { id: 'nyankoface-teams', path: '/git/org/nyankoface/teams', auth: true },
  { id: 'seraphim-members', path: '/git/org/seraphim-labs/members', auth: true },
  { id: 'seraphim-teams', path: '/git/org/seraphim-labs/teams', auth: true },
];

const controlRoutes = [
  { id: 'settings', path: '/git/user/settings', auth: true, expectedWidth: [900, 982] },
  {
    id: 'notifications',
    path: '/git/notifications/subscriptions',
    auth: true,
    expectedWidth: [1100, 1218],
  },
  { id: 'admin', path: '/git/admin', auth: true, expectedWidth: [1100, 1218] },
  {
    id: 'skill-files',
    path: '/git/nyankoface/repository-polish-skill/src/branch/main',
    auth: false,
    checkScreenReaderHeader: true,
  },
];

const viewports = [
  { id: 'mobile-390', width: 390, height: 844 },
  { id: 'desktop-1280', width: 1280, height: 900 },
  { id: 'desktop-1440', width: 1440, height: 1000 },
  { id: 'desktop-1920', width: 1920, height: 1080 },
];

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

const login = async (page) => {
  await page.goto(`${baseUrl}/git/user/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[name="user_name"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await Promise.all([
    page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: /log in|login/i }).click(),
  ]);
};

try {
  for (const viewport of viewports) {
    for (const authenticated of [false, true]) {
      const routes = [...affectedRoutes, ...controlRoutes].filter(
        (route) => route.auth === authenticated,
      );
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        viewport: { width: viewport.width, height: viewport.height },
        colorScheme: 'light',
        reducedMotion: 'reduce',
      });
      const page = await context.newPage();
      if (authenticated) await login(page);

      for (const route of routes) {
        const response = await page.goto(`${baseUrl}${route.path}`, {
          waitUntil: 'domcontentloaded',
        });
        await page.waitForTimeout(350);
        const audit = await page.evaluate(() => {
          const bounds = (element) => {
            if (!element) return null;
            const rect = element.getBoundingClientRect();
            return {
              x: Math.round(rect.x * 10) / 10,
              width: Math.round(rect.width * 10) / 10,
              right: Math.round(rect.right * 10) / 10,
            };
          };
          const pageContent = document.querySelector('.page-content');
          const container =
            pageContent?.querySelector(':scope > .ui.container') ||
            pageContent?.querySelector('.ui.container') ||
            null;
          const pageStyle = pageContent ? getComputedStyle(pageContent) : null;
          const screenReaderHeader = document.querySelector(
            '.repository.file.list #repo-files-table thead.tw-sr-only',
          );
          return {
            viewportWidth: document.documentElement.clientWidth,
            scrollWidth: document.documentElement.scrollWidth,
            horizontalOverflow: Math.max(
              0,
              document.documentElement.scrollWidth - document.documentElement.clientWidth,
            ),
            page: bounds(pageContent),
            container: bounds(container),
            pagePadding: pageStyle
              ? [Number.parseFloat(pageStyle.paddingLeft), Number.parseFloat(pageStyle.paddingRight)]
              : null,
            screenReaderHeader: bounds(screenReaderHeader),
          };
        });

        const defects = [];
        const status = response?.status() ?? 0;
        const expectedStatus = route.expectedStatus || 200;
        if (status !== expectedStatus) defects.push(`HTTP ${status}; expected ${expectedStatus}`);
        if (!audit.page) defects.push('page-content is missing');
        if (!audit.container && !route.narrowForm) defects.push('primary container is missing');
        if (audit.horizontalOverflow > 2) {
          defects.push(`horizontal overflow is ${audit.horizontalOverflow}px`);
        }

        if (affectedRoutes.includes(route)) {
          if (viewport.width >= 768) {
            const expectedPageWidth = Math.min(1280, viewport.width - 64);
            if (audit.page && Math.abs(audit.page.width - expectedPageWidth) > 2) {
              defects.push(`page width is ${audit.page.width}px; expected ${expectedPageWidth}px`);
            }
            if (
              audit.pagePadding &&
              (Math.abs(audit.pagePadding[0] - 32) > 1 ||
                Math.abs(audit.pagePadding[1] - 32) > 1)
            ) {
              defects.push(
                `desktop inner gutter is ${audit.pagePadding.join('px/')}px; expected 32px/32px`,
              );
            }
            if (
              !route.narrowForm &&
              audit.container &&
              audit.container.width < Math.min(1150, expectedPageWidth - 64)
            ) {
              defects.push(`wide container is too narrow at ${audit.container.width}px`);
            }
          } else if (audit.page && audit.page.width < viewport.width - 42) {
            defects.push(`mobile page is too narrow at ${audit.page.width}px`);
          }
        }

        if (route.expectedWidth && viewport.width >= 1280 && audit.container) {
          const [minimum, maximum] = route.expectedWidth;
          if (audit.container.width < minimum || audit.container.width > maximum) {
            defects.push(
              `${route.id} container is ${audit.container.width}px; expected ${minimum}-${maximum}px`,
            );
          }
        }

        if (
          route.checkScreenReaderHeader &&
          viewport.width < 768 &&
          audit.screenReaderHeader?.width > 2
        ) {
          defects.push(
            `screen-reader-only table header is ${audit.screenReaderHeader.width}px wide`,
          );
        }

        const screenshot = `${viewport.id}--${route.id}.png`;
        await page.screenshot({ path: join(outputDir, screenshot), fullPage: true });
        results.push({ viewport, authenticated, route, status, audit, defects, screenshot });
        process.stdout.write(
          `${defects.length ? 'FAIL' : 'PASS'} ${viewport.id.padEnd(14)} ${route.id}\n`,
        );
      }
      await context.close();
    }
  }
} finally {
  await browser.close();
}

for (const route of affectedRoutes) {
  const desktop = results
    .filter(({ route: resultRoute, viewport }) => resultRoute.id === route.id && viewport.width >= 1280)
    .sort((a, b) => a.viewport.width - b.viewport.width);
  for (let index = 1; index < desktop.length; index += 1) {
    const previous = desktop[index - 1];
    const current = desktop[index];
    const previousWidth = route.narrowForm
      ? previous.audit.page.width -
        previous.audit.pagePadding[0] -
        previous.audit.pagePadding[1]
      : previous.audit.container?.width;
    const currentWidth = route.narrowForm
      ? current.audit.page.width - current.audit.pagePadding[0] - current.audit.pagePadding[1]
      : current.audit.container?.width;
    if (previousWidth && currentWidth && currentWidth < previousWidth - 2) {
      current.defects.push(
        `available width shrank from ${previousWidth}px at ${previous.viewport.width}px ` +
          `to ${currentWidth}px at ${current.viewport.width}px`,
      );
    }
  }
}

const passed = results.filter(({ defects }) => defects.length === 0).length;
await writeFile(
  join(outputDir, 'report.json'),
  `${JSON.stringify({ passed, total: results.length, results }, null, 2)}\n`,
);
if (passed !== results.length) process.exitCode = 1;
