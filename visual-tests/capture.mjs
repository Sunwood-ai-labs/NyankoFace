import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { routes, viewports } from './routes.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.VISUAL_QA_OUTPUT_DIR || join(root, 'artifacts'));
const username = process.env.NYANKOFACE_ADMIN_USER || 'nyankoface-admin';
const password = process.env.NYANKOFACE_ADMIN_PASSWORD || 'nyankoface1234';
const selectedViewports = process.env.VISUAL_QA_VIEWPORTS
  ? viewports.filter(({ id }) => process.env.VISUAL_QA_VIEWPORTS.split(',').includes(id))
  : viewports;
const selectedRouteIds = process.env.VISUAL_QA_ROUTES?.split(',').filter(Boolean);
const selectedRoutes = selectedRouteIds ? routes.filter(({ id }) => selectedRouteIds.includes(id)) : routes;

if (selectedRoutes.length === 0 || selectedViewports.length === 0) {
  throw new Error('No visual QA routes or viewports were selected.');
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });

const browser = await chromium.launch({ headless: true });
const results = [];

async function authenticatedStorageState() {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  await page.goto(`${baseUrl}/git/user/login`, {
    waitUntil: 'domcontentloaded',
  });
  await page.locator('input[name="user_name"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await Promise.all([
    page.waitForLoadState('domcontentloaded'),
    page.getByRole('button', { name: /log in|login/i }).click(),
  ]);
  if (page.url().includes('/user/login')) {
    throw new Error('Forgejo login did not complete for authenticated visual routes');
  }
  const storageState = await context.storageState();
  await context.close();
  return storageState;
}

try {
  const authState = selectedRoutes.some(({ authenticated }) => authenticated)
    ? await authenticatedStorageState()
    : null;
  for (const viewport of selectedViewports) {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: viewport.width, height: viewport.height },
      colorScheme: 'light',
      reducedMotion: 'reduce',
    });

    for (const route of selectedRoutes) {
      const routeContext = route.authenticated
        ? await browser.newContext({
          ignoreHTTPSErrors: true,
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: 'light',
          reducedMotion: 'reduce',
          storageState: authState,
        })
        : context;
      const page = await routeContext.newPage();
      if (route.theme) {
        await page.addInitScript((theme) => {
          localStorage.setItem('nyankoface-theme-v2', theme);
          document.cookie = `nyankoface-theme=${theme}; Path=/; Max-Age=31536000; SameSite=Lax`;
        }, route.theme);
      }
      const consoleErrors = [];
      const pageErrors = [];
      const failedRequests = [];
      const httpErrors = [];
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      page.on('pageerror', (error) => pageErrors.push(error.message));
      page.on('requestfailed', (request) => {
        const failure = request.failure()?.errorText || 'unknown failure';
        if (!failure.includes('ERR_ABORTED')) failedRequests.push(`${request.method()} ${request.url()}: ${failure}`);
      });
      page.on('response', (networkResponse) => {
        if (networkResponse.status() >= 400) httpErrors.push(`${networkResponse.status()} ${networkResponse.url()}`);
      });

      const startedAt = Date.now();
      let response = null;
      let navigationError = null;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          response = await page.goto(`${baseUrl}${route.path}`, {
            // The hub intentionally keeps runtime/status requests alive. Waiting
            // for networkidle can therefore consume the entire CI job even
            // though the page is already ready to inspect.
            waitUntil: route.waitUntil || 'domcontentloaded',
            timeout: 45_000,
          });
          navigationError = null;
          break;
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          const transientNetworkChange = message.includes('ERR_NETWORK_CHANGED') || message.includes('ERR_CONNECTION_RESET');
          navigationError = message;
          if (!transientNetworkChange || attempt === 1) break;
          await page.waitForTimeout(750);
        }
      }
      if (route.settleMs) await page.waitForTimeout(route.settleMs);
      if (route.waitSelector) {
        await page.locator(route.waitSelector).waitFor({
          state: 'visible',
          timeout: 30_000,
        });
      }
      await page.evaluate(() => document.fonts?.ready).catch(() => undefined);
      if (route.id === 'community-detail' || route.id.startsWith('community-markdown')) {
        await page.evaluate(() => {
          const slugs = ['luna-scout', 'patch-orbit', 'mikan-reviewer'];
          for (const slug of slugs) {
            for (const image of document.querySelectorAll(`a[href$="/${slug}"] img`)) {
              image.loading = 'eager';
            }
          }
        });
        await page.waitForFunction(() => {
          const slugs = ['luna-scout', 'patch-orbit', 'mikan-reviewer'];
          return slugs.every((slug) => Array.from(
            document.querySelectorAll(`a[href$="/${slug}"] img`),
          ).some((image) => image.complete && image.naturalWidth > 0));
        }, undefined, { timeout: 5_000 }).catch(() => undefined);
      }

      let disclosureOpen = null;
      let disclosureCount = null;
      const shouldOpenDisclosure = route.openDisclosureSelector &&
        (!route.openDisclosureViewport || route.openDisclosureViewport === viewport.id);
      if (shouldOpenDisclosure) {
        const summary = page.locator(route.openDisclosureSelector);
        disclosureCount = await summary.count();
        if (disclosureCount === 1) {
          await summary.click();
          disclosureOpen = await summary.evaluate((element) => element.parentElement?.hasAttribute('open') || false);
        }
      }

      const screenshotName = `${viewport.id}--${route.id}.png`;
      const screenshotPath = join(outputDir, 'screenshots', screenshotName);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      const pageState = await page.evaluate(() => {
        const bodyText = document.body?.innerText || '';
        const heading = document.querySelector('h1')?.textContent?.trim() || null;
        const viewportWidth = document.documentElement.clientWidth;
        const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
        const visibleAppTabLabels = Array.from(document.querySelectorAll('.nyankoface-app-tab'))
          .filter((element) => element.getBoundingClientRect().width > 0)
          .map((element) => element.textContent?.trim() || '')
          .filter(Boolean);
        const pullTabLabels = Array.from(document.querySelectorAll('.ui.top.attached.pull.tabular.menu > .item'))
          .map((element) => element.textContent?.replace(/\s+/g, ' ').trim() || '')
          .filter(Boolean);
        const visiblePullTabLabels = Array.from(document.querySelectorAll('.ui.top.attached.pull.tabular.menu > .item'))
          .filter((element) => window.getComputedStyle(element).display !== 'none')
          .map((element) => element.textContent?.replace(/\s+/g, ' ').trim() || '')
          .filter(Boolean);
        const pullDiffBoxes = Array.from(document.querySelectorAll('.diff-file-box'));
        const hfChangeTotals = document.querySelector('.nyankoface-hf-change-totals')?.textContent?.replace(/\s+/g, ' ').trim() || '';
        const virtualAgentSlugs = ['luna-scout', 'patch-orbit', 'mikan-reviewer'];
        const virtualAgentAuthors = virtualAgentSlugs.filter((slug) =>
          document.querySelector(`.timeline-item.comment .author[href$="/${slug}"]`),
        );
        const virtualAgentAvatars = virtualAgentSlugs.map((slug) => {
          const image = document.querySelector(`a[href$="/${slug}"] img`);
          return image ? { slug, src: image.getAttribute('src'), loaded: image.complete && image.naturalWidth > 0 } : null;
        }).filter(Boolean);
        const issueCommentCounts = Array.from(document.querySelectorAll(
          '#issue-list .nyankoface-community-comment-count, #issue-list a.flex-text-block',
        ))
          .map((element) => Number(element.textContent?.match(/[0-9]+/)?.[0] || 0));
        const markdownSurface = document.querySelector('.issue-content-left, .ui.timeline');
        const skillRelationshipMap = Array.from(document.querySelectorAll('[data-skill-relationship-map]'))
          .find((element) => {
            const style = window.getComputedStyle(element);
            return style.display !== 'none' && element.getBoundingClientRect().height > 0;
          });
        const primaryRail = document.querySelector('main[data-nyankoface-page-frame], .page-content');
        const primaryRailRect = primaryRail?.getBoundingClientRect();
        const primaryRailStyle = primaryRail ? getComputedStyle(primaryRail) : null;
        const leftInset = primaryRailRect && primaryRailStyle
          ? primaryRailRect.left + (Number.parseFloat(primaryRailStyle.paddingLeft) || 0)
          : null;
        const rightInset = primaryRailRect && primaryRailStyle
          ? viewportWidth - primaryRailRect.right + (Number.parseFloat(primaryRailStyle.paddingRight) || 0)
          : null;
        return {
          title: document.title,
          nyankoFaceTheme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
          heading,
          viewportWidth,
          scrollWidth,
          horizontalOverflow: Math.max(0, scrollWidth - viewportWidth),
          primaryRail: primaryRail ? {
            selector: primaryRail.matches('main[data-nyankoface-page-frame]') ? 'portal-main' : 'forgejo-page-content',
            leftInset: Math.round(leftInset),
            rightInset: Math.round(rightInset),
            minimumInset: Math.round(Math.min(leftInset, rightInset)),
          } : null,
          repositoryNotFound: bodyText.includes('Repository not found'),
          applicationUnavailable: bodyText.includes('Application unavailable'),
          runningBadgeVisible: bodyText.includes('CPU · Running'),
          onDemandStageVisible: bodyText.includes('This Space runs on demand'),
          communityPage: document.body?.getAttribute('data-nyankoface-community-page') || null,
          communityKind: document.body?.getAttribute('data-nyankoface-community-kind') || null,
          pullView: document.body?.getAttribute('data-nyankoface-pull-view') || null,
          issueRowCount: document.querySelectorAll('#issue-list .flex-item').length,
          issueCommentCounts,
          virtualAgentAuthors,
          virtualAgentAvatars,
          markdownBlockquotes: markdownSurface?.querySelectorAll('.comment-body blockquote').length || 0,
          markdownLists: markdownSurface?.querySelectorAll('.comment-body ul, .comment-body ol').length || 0,
          markdownTaskItems: markdownSurface?.querySelectorAll('.comment-body input[type="checkbox"]').length || 0,
          markdownCodeBlocks: markdownSurface?.querySelectorAll('.comment-body pre').length || 0,
          markdownTables: markdownSurface?.querySelectorAll('.comment-body table').length || 0,
          markdownLinks: markdownSurface?.querySelectorAll('.comment-body a[href]').length || 0,
          markdownDetails: markdownSurface?.querySelectorAll('.comment-body details').length || 0,
          visibleAppTabLabels,
          pullTabLabels,
          visiblePullTabLabels,
          pullCommitLinkVisible: Boolean(document.querySelector('.nyankoface-pull-commit-link')),
          hfFileSummaryRows: document.querySelectorAll('.nyankoface-hf-file-row').length,
          hfChangedTags: document.querySelectorAll('.nyankoface-hf-changed-tag').length,
          hfDiffBoxes: pullDiffBoxes.length,
          hfSplitDiff: pullDiffBoxes.length > 0 && pullDiffBoxes.every((box) => box.querySelector('.file-body')?.classList.contains('code-diff-split')),
          hfChangeTotals,
          skillRelationshipMapVisible: Boolean(skillRelationshipMap),
          skillRelationshipLinks: skillRelationshipMap?.querySelectorAll('[data-skill-relationship-link]').length || 0,
          skillRelationshipPlacement: skillRelationshipMap?.getAttribute('data-relationship-placement') || null,
          skillRelationshipInAside: Boolean(skillRelationshipMap?.closest('aside')),
          skillDependencyBadges: document.querySelectorAll('[data-skill-dependency-count]').length,
          bodyPreview: bodyText.replace(/\s+/g, ' ').trim().slice(0, 240),
        };
      }).catch(() => ({
        title: null,
        nyankoFaceTheme: 'standard',
        heading: null,
        viewportWidth: viewport.width,
        scrollWidth: viewport.width,
        horizontalOverflow: 0,
        repositoryNotFound: false,
        applicationUnavailable: false,
        runningBadgeVisible: false,
        onDemandStageVisible: false,
        communityPage: null,
        communityKind: null,
        pullView: null,
        issueRowCount: 0,
        issueCommentCounts: [],
        virtualAgentAuthors: [],
        virtualAgentAvatars: [],
        markdownBlockquotes: 0,
        markdownLists: 0,
        markdownTaskItems: 0,
        markdownCodeBlocks: 0,
        markdownTables: 0,
        markdownLinks: 0,
        markdownDetails: 0,
        visibleAppTabLabels: [],
        pullTabLabels: [],
        visiblePullTabLabels: [],
        pullCommitLinkVisible: false,
        hfFileSummaryRows: 0,
        hfChangedTags: 0,
        hfDiffBoxes: 0,
        hfSplitDiff: false,
        hfChangeTotals: '',
        skillRelationshipMapVisible: false,
        skillRelationshipLinks: 0,
        skillRelationshipPlacement: null,
        skillRelationshipInAside: false,
        skillDependencyBadges: 0,
        bodyPreview: '',
      }));

      const status = response?.status() ?? null;
      const defects = [];
      const requiredInset = viewport.width < 768 ? 20 : 24;
      if (navigationError) defects.push(`Navigation failed: ${navigationError}`);
      if (status === null || status >= 400) defects.push(`Unexpected HTTP status: ${status ?? 'none'}`);
      if (pageState.horizontalOverflow > 2) defects.push(`Horizontal overflow: ${pageState.horizontalOverflow}px`);
      if (!route.allowFullBleed && !pageState.primaryRail) defects.push('Primary content rail is missing');
      if (!route.allowFullBleed && pageState.primaryRail?.minimumInset < requiredInset) {
        defects.push(`Content safe area: ${pageState.primaryRail.minimumInset}px; expected at least ${requiredInset}px`);
      }
      if (route.theme && pageState.nyankoFaceTheme !== route.theme) defects.push(`Expected ${route.theme} theme but found ${pageState.nyankoFaceTheme}`);
      if (shouldOpenDisclosure && disclosureCount !== 1) defects.push(`Expected one disclosure control but found ${disclosureCount}`);
      if (shouldOpenDisclosure && disclosureOpen !== true) defects.push('Disclosure control did not open after click');
      if (pageState.repositoryNotFound) defects.push('Repository not found empty state is visible');
      if (pageState.applicationUnavailable) defects.push('Embedded application is unavailable');
      if (pageState.runningBadgeVisible && pageState.onDemandStageVisible) defects.push('Runtime badge says Running while the on-demand placeholder is visible');
      if (route.id === 'community-list' && pageState.communityPage !== 'list') defects.push('Community list marker is missing');
      if (route.id === 'community-list' && pageState.issueRowCount < 1) defects.push('Community list has no seeded issue rows');
      if (route.id === 'community-list' && !pageState.issueCommentCounts.includes(3)) defects.push('Seeded three-reply discussion count is missing');
      if (route.id === 'community-detail' && pageState.communityPage !== 'detail') defects.push('Community detail marker is missing');
      if (route.id === 'community-detail' && pageState.virtualAgentAuthors.length !== 3) defects.push('All three virtual-agent participants are not visible');
      if (route.id === 'community-detail' && new Set(pageState.virtualAgentAvatars.map(({ src }) => src)).size !== 3) defects.push('Virtual-agent avatars are not distinct');
      if (route.id === 'community-detail' && pageState.virtualAgentAvatars.some(({ loaded }) => !loaded)) defects.push('A virtual-agent avatar failed to load');
      if (route.id.startsWith('pull-') && pageState.communityPage !== 'detail') defects.push('Pull request detail marker is missing');
      if (route.id.startsWith('pull-') && pageState.pullTabLabels.length !== 3) defects.push(`Expected three pull request tabs but found ${pageState.pullTabLabels.length}`);
      if (route.id.startsWith('pull-') && pageState.communityKind !== 'pull') defects.push('Pull request community-kind marker is missing');
      if (route.id.startsWith('pull-') && pageState.visiblePullTabLabels.length !== 2) defects.push(`Expected two Hugging Face-style primary pull tabs but found ${pageState.visiblePullTabLabels.length}`);
      if (route.id.startsWith('pull-') && !pageState.pullCommitLinkVisible) defects.push('Pull request commit-history metadata link is missing');
      if (route.id === 'pull-detail' && pageState.pullView !== 'conversation') defects.push('Pull request conversation marker is missing');
      if (route.id === 'pull-commits' && pageState.pullView !== 'commits') defects.push('Pull request commits marker is missing');
      if (route.id === 'pull-files' && pageState.pullView !== 'files') defects.push('Pull request files marker is missing');
      if (route.id === 'pull-files' && pageState.hfFileSummaryRows < 1) defects.push('Hugging Face-style changed-file summary is missing');
      if (route.id === 'pull-files' && pageState.hfChangedTags !== pageState.hfDiffBoxes) defects.push('Not every diff file has a CHANGED marker');
      if (route.id === 'pull-files' && !pageState.hfSplitDiff) defects.push('Pull request is not using the Hugging Face-style split diff');
      if (route.id === 'pull-files' && !/^\+\d+\s*-\d+$/.test(pageState.hfChangeTotals)) defects.push('Pull request change totals do not show both additions and deletions');
      if (route.id.startsWith('community-markdown') && pageState.communityPage !== 'detail') defects.push('Markdown discussion detail marker is missing');
      if (route.id.startsWith('community-markdown') && pageState.virtualAgentAuthors.length !== 3) defects.push('Markdown discussion does not show all three agent participants');
      if (route.id.startsWith('community-markdown') && pageState.markdownBlockquotes < 1) defects.push('Markdown blockquote is missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownLists < 3) defects.push('Markdown list variants are missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownTaskItems < 3) defects.push('Markdown task list is missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownCodeBlocks < 2) defects.push('Markdown code block variants are missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownTables < 1) defects.push('Markdown table is missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownLinks < 2) defects.push('Markdown links or mention are missing');
      if (route.id.startsWith('community-markdown') && pageState.markdownDetails < 1) defects.push('Markdown disclosure is missing');
      if (route.id.startsWith('community-') && route.path.includes('/qr-code-generator/') && !pageState.visibleAppTabLabels.includes('App')) defects.push('Space repository tab is not labeled App');
      if (route.id === 'skills' && pageState.skillDependencyBadges < 10) defects.push('Skills directory does not expose dependency status for every seeded Skill');
      if (route.id.startsWith('skill-detail') && !pageState.skillRelationshipMapVisible) defects.push('Skill relationship map is missing');
      if (route.id.startsWith('skill-detail') && viewport.width >= 1024 && (pageState.skillRelationshipPlacement !== 'sidebar' || !pageState.skillRelationshipInAside)) defects.push('Desktop Skill relationships are not in the sidebar');
      if (route.id.startsWith('skill-detail') && viewport.width < 1024 && (pageState.skillRelationshipPlacement !== 'mobile' || pageState.skillRelationshipInAside)) defects.push('Mobile Skill relationships are not in the main content flow');
      const minimumSkillRelationshipLinks = route.id === 'skill-detail-no-readme' ? 1 : 3;
      if (route.id.startsWith('skill-detail') && pageState.skillRelationshipLinks < minimumSkillRelationshipLinks) defects.push('Skill relationship map does not contain the seeded dependency links');
      if (pageErrors.length) defects.push(`${pageErrors.length} uncaught page error(s)`);
      if (httpErrors.length) defects.push(`${httpErrors.length} HTTP resource error(s)`);

      const result = {
        id: route.id,
        label: route.label,
        path: route.path,
        requestedUrl: `${baseUrl}${route.path}`,
        finalUrl: page.url(),
        viewport,
        focus: route.focus,
        disclosureCount,
        disclosureOpen,
        status,
        durationMs: Date.now() - startedAt,
        screenshot: relative(outputDir, screenshotPath).replaceAll('\\', '/'),
        ...pageState,
        consoleErrors,
        pageErrors,
        failedRequests,
        httpErrors,
        defects,
        passed: defects.length === 0,
      };
      results.push(result);
      process.stdout.write(`${result.passed ? 'PASS' : 'FAIL'} ${viewport.id.padEnd(7)} ${route.id} (${result.durationMs}ms)\n`);
      await page.close();
      if (routeContext !== context) await routeContext.close();
    }

    await context.close();
  }
} finally {
  await browser.close();
}

const manifest = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  baseUrl,
  summary: {
    total: results.length,
    passed: results.filter(({ passed }) => passed).length,
    failed: results.filter(({ passed }) => !passed).length,
    screenshots: results.length,
  },
  results,
};

await writeFile(join(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);

const markdown = [
  '# NyankoFace visual QA — agent review packet',
  '',
  `Generated: \`${manifest.generatedAt}\`  `,
  `Base URL: \`${baseUrl}\`  `,
  `Result: **${manifest.summary.passed}/${manifest.summary.total} passed**`,
  '',
  '## Agent review instructions',
  '',
  '1. Open every screenshot below; do not infer visual quality from HTTP status alone.',
  '2. Compare the screenshot with the stated review focus.',
  '3. Report clipping, blur, overlap, broken assets, inconsistent spacing, wrong navigation, and misleading runtime state.',
  '4. Use `manifest.json` for exact URLs, viewport sizes, console errors, failed requests, and overflow measurements.',
  '5. For each issue, cite the screenshot filename and describe the visible evidence.',
  '',
  '## Capture index',
  '',
  '| Result | Viewport | Screen | HTTP | Overflow | Screenshot |',
  '|---|---|---|---:|---:|---|',
  ...results.map((result) => `| ${result.passed ? 'PASS' : 'FAIL'} | ${result.viewport.id} (${result.viewport.width}×${result.viewport.height}) | ${result.label} | ${result.status ?? '—'} | ${result.horizontalOverflow}px | [${result.screenshot}](${result.screenshot}) |`),
  '',
  '## Screenshots',
  '',
  ...results.flatMap((result) => [
    `### ${result.viewport.id} / ${result.label}`,
    '',
    `- Route: \`${result.path}\``,
    `- Review focus: ${result.focus}`,
    `- Automated defects: ${result.defects.length ? result.defects.join('; ') : 'none'}`,
    `- Browser observations: ${result.consoleErrors.length} console error(s), ${result.failedRequests.length} failed request(s), ${result.httpErrors.length} HTTP resource error(s)`,
    '',
    `![${result.viewport.id} ${result.label}](${result.screenshot})`,
    '',
  ]),
];
await writeFile(join(outputDir, 'AGENT_REVIEW.md'), `${markdown.join('\n')}\n`);

process.stdout.write(`\nVisual QA packet: ${join(outputDir, 'AGENT_REVIEW.md')}\n`);
process.stdout.write(`Manifest: ${join(outputDir, 'manifest.json')}\n`);

if (manifest.summary.failed > 0) process.exitCode = 1;
