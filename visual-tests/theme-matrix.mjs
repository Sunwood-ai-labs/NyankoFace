import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { routes, themes, viewports } from './routes.mjs';
import { generateContactSheets } from './contact-sheets.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.THEME_QA_OUTPUT_DIR || join(root, 'artifacts', 'theme-matrix'));
const concurrency = Math.max(1, Number(process.env.THEME_QA_CONCURRENCY || 4));
const select = (values, envName) => {
  const ids = process.env[envName]?.split(',').map((value) => value.trim()).filter(Boolean);
  return ids ? values.filter(({ id }) => ids.includes(id)) : values;
};
const selectedThemes = select(themes, 'VISUAL_QA_THEMES');
const selectedViewports = select(viewports, 'VISUAL_QA_VIEWPORTS');
const selectedRoutes = select(routes, 'VISUAL_QA_ROUTES');
const selectedColorSchemes = select([
  { id: 'light', label: 'Light OS' },
  { id: 'dark', label: 'Dark OS' },
], 'VISUAL_QA_COLOR_SCHEMES');

if (!selectedThemes.length || !selectedViewports.length || !selectedRoutes.length || !selectedColorSchemes.length) {
  throw new Error('Theme QA selection produced an empty theme, OS color scheme, viewport, or route list.');
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });

const browser = await chromium.launch({ headless: true });
const results = [];

const inspectPage = () => {
  const parseColor = (value) => {
    const parts = value.match(/[\d.]+/g)?.map(Number) || [];
    if (parts.length < 3) return null;
    return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
  };
  const luminance = ({ r, g, b }) => {
    const channel = (value) => {
      const normalized = value / 255;
      return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const contrast = (foreground, background) => {
    const light = Math.max(luminance(foreground), luminance(background));
    const dark = Math.min(luminance(foreground), luminance(background));
    return (light + 0.05) / (dark + 0.05);
  };
  const composite = (foreground, background) => {
    const alpha = foreground.a + background.a * (1 - foreground.a);
    if (alpha <= 0) return { r: 255, g: 255, b: 255, a: 1 };
    return {
      r: (foreground.r * foreground.a + background.r * background.a * (1 - foreground.a)) / alpha,
      g: (foreground.g * foreground.a + background.g * background.a * (1 - foreground.a)) / alpha,
      b: (foreground.b * foreground.a + background.b * background.a * (1 - foreground.a)) / alpha,
      a: alpha,
    };
  };
  const effectiveBackground = (element) => {
    const ancestors = [];
    let current = element;
    while (current) {
      ancestors.unshift(current);
      current = current.parentElement;
    }
    let result = { r: 255, g: 255, b: 255, a: 1 };
    let hasImage = false;
    for (const ancestor of ancestors) {
      const ancestorStyle = getComputedStyle(ancestor);
      const color = parseColor(ancestorStyle.backgroundColor);
      const ancestorHasImage = ancestorStyle.backgroundImage !== 'none';
      if (color && color.a >= 0.99) {
        result = color;
        hasImage = ancestorHasImage;
      } else {
        if (ancestorHasImage) hasImage = true;
        if (color && color.a > 0) result = composite(color, result);
      }
    }
    return { color: result, hasImage };
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => node.textContent?.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  });
  const candidateSet = new Set();
  while (walker.nextNode()) {
    const parent = walker.currentNode.parentElement;
    if (parent && !['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG'].includes(parent.tagName)) candidateSet.add(parent);
  }
  const candidates = Array.from(candidateSet);
  const contrastRisks = [];
  const auditedContrasts = [];
  let imageBackedTextCount = 0;
  for (const element of candidates) {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text || text.length > 240 || rect.width < 2 || rect.height < 2) continue;
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) < 0.5) continue;
    if (element.matches(':disabled, [aria-disabled="true"]')) continue;
    if (element.closest('[aria-hidden="true"]')) continue;
    const foreground = parseColor(style.color);
    const backgroundResult = effectiveBackground(element);
    if (!foreground || !backgroundResult.color) continue;
    if (backgroundResult.hasImage) {
      imageBackedTextCount += 1;
      continue;
    }
    const background = backgroundResult.color;
    const effectiveForeground = composite(foreground, background);
    const ratio = contrast(effectiveForeground, background);
    const fontSize = Number.parseFloat(style.fontSize) || 16;
    const fontWeight = Number.parseInt(style.fontWeight, 10) || (style.fontWeight === 'bold' ? 700 : 400);
    const largeText = fontSize >= 24 || (fontSize >= 18.66 && fontWeight >= 700);
    const requiredRatio = largeText ? 3 : 4.5;
    auditedContrasts.push({ ratio, requiredRatio });
    if (ratio + 0.01 < requiredRatio) {
      contrastRisks.push({
        tag: element.tagName.toLowerCase(),
        className: String(element.className || '').slice(0, 100),
        parentClassName: String(element.parentElement?.className || '').slice(0, 120),
        ancestry: Array.from({ length: 4 }, (_, index) => {
          let ancestor = element;
          for (let step = 0; step < index; step += 1) ancestor = ancestor?.parentElement;
          if (!ancestor) return '';
          const id = ancestor.id ? `#${ancestor.id}` : '';
          const classes = typeof ancestor.className === 'string' && ancestor.className.trim()
            ? `.${ancestor.className.trim().split(/\s+/).slice(0, 4).join('.')}`
            : '';
          return `${ancestor.tagName.toLowerCase()}${id}${classes}`;
        }).filter(Boolean).join(' > '),
        text: text.slice(0, 90),
        foreground: style.color,
        background: `rgb(${background.r}, ${background.g}, ${background.b})`,
        ratio: Number(ratio.toFixed(2)),
        requiredRatio,
        fontSize,
        fontWeight,
      });
    }
  }
  const bodyText = document.body?.innerText?.replace(/\s+/g, ' ').trim() || '';
  const viewportWidth = document.documentElement.clientWidth;
  const scrollWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
  const primaryRail = document.querySelector('main[data-nyankoface-page-frame], .page-content');
  const primaryRailRect = primaryRail?.getBoundingClientRect();
  const primaryRailStyle = primaryRail ? getComputedStyle(primaryRail) : null;
  const leftInset = primaryRailRect && primaryRailStyle
    ? primaryRailRect.left + (Number.parseFloat(primaryRailStyle.paddingLeft) || 0)
    : null;
  const rightInset = primaryRailRect && primaryRailStyle
    ? viewportWidth - primaryRailRect.right + (Number.parseFloat(primaryRailStyle.paddingRight) || 0)
    : null;
  const organizationPage = document.body?.hasAttribute('data-nyankoface-org');
  const organizationContent = organizationPage ? document.querySelector('.page-content.organization, .page-content') : null;
  const organizationRect = organizationContent?.getBoundingClientRect();
  const memberCountText = document.querySelector('.nyankoface-org-hf-sidebar h2 span')?.textContent?.trim() || '';
  return {
    title: document.title,
    theme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
    bodyTextLength: bodyText.length,
    bodyPreview: bodyText.slice(0, 220),
    viewportWidth,
    scrollWidth,
    horizontalOverflow: Math.max(0, scrollWidth - viewportWidth),
    primaryRail: primaryRail ? {
      selector: primaryRail.matches('main[data-nyankoface-page-frame]') ? 'portal-main' : 'forgejo-page-content',
      leftInset: Math.round(leftInset),
      rightInset: Math.round(rightInset),
      minimumInset: Math.round(Math.min(leftInset, rightInset)),
    } : null,
    contrastRiskCount: contrastRisks.length,
    auditedTextCount: auditedContrasts.length,
    imageBackedTextCount,
    minimumContrast: auditedContrasts.length
      ? Number(Math.min(...auditedContrasts.map(({ ratio }) => ratio)).toFixed(2))
      : null,
    minimumContrastMargin: auditedContrasts.length
      ? Number(Math.min(...auditedContrasts.map(({ ratio, requiredRatio }) => ratio / requiredRatio)).toFixed(2))
      : null,
    lowestContrast: contrastRisks.length ? Math.min(...contrastRisks.map(({ ratio }) => ratio)) : null,
    contrastRisks: contrastRisks.slice(0, 50),
    repositoryNotFound: bodyText.includes('Repository not found'),
    applicationUnavailable: bodyText.includes('Application unavailable'),
    organizationAudit: organizationPage ? {
      mobileSideGutter: viewportWidth <= 767 && organizationRect
        ? Math.round(Math.max(Math.abs(organizationRect.left), Math.abs(viewportWidth - organizationRect.right)))
        : 0,
      memberPlaceholders: document.querySelectorAll('.nyankoface-member-cloud > span').length,
      memberAvatars: document.querySelectorAll('.nyankoface-member-cloud > img, .nyankoface-member-cloud > a > img').length,
      memberHrefs: Array.from(document.querySelectorAll('.nyankoface-member-cloud > a'))
        .map((element) => new URL(element.href).pathname.replace(/^\/git\//, '')),
      unloadedMemberAvatars: Array.from(document.querySelectorAll('.nyankoface-member-cloud img'))
        .filter((image) => !image.complete || image.naturalWidth < 1).length,
      declaredMembers: Number.parseInt(memberCountText, 10) || 0,
    } : null,
  };
};

const captureRoute = async ({ context, route, theme, colorScheme, viewport }) => {
  const page = await context.newPage();
  page.setDefaultTimeout(8_000);
  page.setDefaultNavigationTimeout(30_000);
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText || 'unknown failure';
    if (!failure.includes('ERR_ABORTED')) failedRequests.push(`${request.method()} ${request.url()}: ${failure}`);
  });

  const startedAt = Date.now();
  let response = null;
  let navigationError = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      response = await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'domcontentloaded' });
      navigationError = null;
      if (response.status() >= 500 && attempt === 0) {
        await page.waitForTimeout(1200);
        continue;
      }
      break;
    } catch (error) {
      navigationError = error instanceof Error ? error.message : String(error);
      if (attempt === 0) await page.waitForTimeout(600);
    }
  }
  await page.waitForTimeout(route.settleMs || 450);
  await page.evaluate(() => document.fonts?.ready).catch(() => undefined);

  const transientRuntimeFailure =
    pageErrors.some((message) => /preload|502|bad gateway/i.test(message)) ||
    consoleErrors.some((message) => /502|bad gateway/i.test(message));
  if (transientRuntimeFailure) {
    pageErrors.length = 0;
    consoleErrors.length = 0;
    failedRequests.length = 0;
    response = await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(Math.max(route.settleMs || 450, 1_500));
    await page.evaluate(() => document.fonts?.ready).catch(() => undefined);
  }

  let disclosureOpen = null;
  const shouldOpenDisclosure = route.openDisclosureSelector &&
    (!route.openDisclosureViewport || route.openDisclosureViewport === viewport.id);
  if (shouldOpenDisclosure) {
    const summary = page.locator(route.openDisclosureSelector);
    if (await summary.count() === 1) {
      await summary.click();
      disclosureOpen = await summary.evaluate((element) => element.parentElement?.hasAttribute('open') || false);
    }
  }

  if (route.focusSelector) {
    const focusTargets = page.locator(route.focusSelector);
    if (await focusTargets.count() > 0) await focusTargets.first().focus();
  }

  const screenshotName = `${theme.id}--${colorScheme.id}--${viewport.id}--${route.id}.png`;
  const screenshotPath = join(outputDir, 'screenshots', screenshotName);
  await page.screenshot({ path: screenshotPath, fullPage: true });
  const state = await page.evaluate(inspectPage).catch(() => ({
    title: null,
    theme: 'unknown',
    bodyTextLength: 0,
    bodyPreview: '',
    viewportWidth: viewport.width,
    scrollWidth: viewport.width,
    horizontalOverflow: 0,
    contrastRisks: [],
    contrastRiskCount: 0,
    auditedTextCount: 0,
    imageBackedTextCount: 0,
    minimumContrast: null,
    minimumContrastMargin: null,
    lowestContrast: null,
    repositoryNotFound: false,
    applicationUnavailable: false,
  }));
  const defects = [];
  const requiredInset = viewport.width < 768 ? 20 : 24;
  const status = response?.status() ?? null;
  if (navigationError) defects.push(`Navigation failed: ${navigationError}`);
  if (status === null || status >= 400) defects.push(`Unexpected HTTP status: ${status ?? 'none'}`);
  if (route.themeAware !== false && state.theme !== theme.id) defects.push(`Expected ${theme.id} theme but found ${state.theme}`);
  if (state.bodyTextLength < 20) defects.push('Page is blank or nearly blank');
  if (state.horizontalOverflow > 2) defects.push(`Horizontal overflow: ${state.horizontalOverflow}px`);
  if (!route.allowFullBleed && !state.primaryRail) defects.push('Primary content rail is missing');
  if (!route.allowFullBleed && state.primaryRail?.minimumInset < requiredInset) {
    defects.push(`Content safe area: ${state.primaryRail.minimumInset}px; expected at least ${requiredInset}px`);
  }
  if (state.contrastRiskCount) defects.push(`${state.contrastRiskCount} WCAG text contrast failure(s)`);
  if (state.repositoryNotFound) defects.push('Repository not found state is visible');
  if (state.applicationUnavailable) defects.push('Application unavailable state is visible');
  if (state.organizationAudit && state.viewportWidth < 768 && state.organizationAudit.mobileSideGutter < 20) {
    defects.push(`Organization mobile safe area: ${state.organizationAudit.mobileSideGutter}px (minimum 20px)`);
  }
  if (state.organizationAudit?.memberPlaceholders) defects.push(`Organization has ${state.organizationAudit.memberPlaceholders} fake member placeholder(s)`);
  if (state.organizationAudit && state.organizationAudit.memberAvatars !== state.organizationAudit.declaredMembers) {
    defects.push(`Organization declares ${state.organizationAudit.declaredMembers} member(s) but renders ${state.organizationAudit.memberAvatars} avatar(s)`);
  }
  if (state.organizationAudit?.unloadedMemberAvatars) {
    defects.push(`Organization has ${state.organizationAudit.unloadedMemberAvatars} unloaded member avatar(s)`);
  }
  if (route.id === 'organization-seraphim') {
    const expectedMembers = ['aurelia-vale', 'cassian-reed', 'ilyana-noor', 'lucien-sol'];
    const actualMembers = [...(state.organizationAudit?.memberHrefs || [])].sort();
    if (JSON.stringify(actualMembers) !== JSON.stringify(expectedMembers)) {
      defects.push(`Seraphim member identities mismatch: ${actualMembers.join(', ') || 'none'}`);
    }
  }
  if (shouldOpenDisclosure && disclosureOpen !== true) defects.push('Disclosure did not open');
  if (pageErrors.length) defects.push(`${pageErrors.length} uncaught page error(s)`);

  const result = {
    route: { id: route.id, label: route.label, path: route.path, focus: route.focus },
    requestedUrl: `${baseUrl}${route.path}`,
    finalUrl: page.url(),
    status,
    durationMs: Date.now() - startedAt,
    disclosureOpen,
    screenshot: relative(outputDir, screenshotPath).replaceAll('\\', '/'),
    ...state,
    theme,
    colorScheme,
    viewport,
    consoleErrors,
    pageErrors,
    failedRequests,
    defects,
    passed: defects.length === 0,
  };
  process.stdout.write(`${result.passed ? 'PASS' : 'FAIL'} ${theme.id.padEnd(10)} ${colorScheme.id.padEnd(5)} ${viewport.id.padEnd(7)} ${route.id}\n`);
  if (!result.passed && result.contrastRisks.length) {
    process.stdout.write(`  Contrast: ${JSON.stringify(result.contrastRisks)}\n`);
  }
  await page.close();
  return result;
};

try {
  for (const theme of selectedThemes) {
    for (const colorScheme of selectedColorSchemes) {
      for (const viewport of selectedViewports) {
        const context = await browser.newContext({
          ignoreHTTPSErrors: true,
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: colorScheme.id,
          reducedMotion: 'reduce',
        });
        await context.addInitScript((themeId) => {
          localStorage.setItem('nyankoface-theme-v2', themeId);
          localStorage.setItem('nyankoface-theme', themeId);
          document.cookie = `nyankoface-theme=${themeId}; Path=/; Max-Age=31536000; SameSite=Lax`;
        }, theme.id);
        let nextIndex = 0;
        const workers = Array.from({ length: Math.min(concurrency, selectedRoutes.length) }, async () => {
          while (nextIndex < selectedRoutes.length) {
            const route = selectedRoutes[nextIndex];
            nextIndex += 1;
            results.push(await captureRoute({ context, route, theme, colorScheme, viewport }));
          }
        });
        await Promise.all(workers);
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
}

results.sort((a, b) =>
  a.theme.id.localeCompare(b.theme.id) ||
  a.colorScheme.id.localeCompare(b.colorScheme.id) ||
  a.viewport.id.localeCompare(b.viewport.id) ||
  a.route.id.localeCompare(b.route.id));

const manifest = {
  schemaVersion: 2,
  generatedAt: new Date().toISOString(),
  baseUrl,
  dimensions: {
    themes: selectedThemes.map(({ id }) => id),
    colorSchemes: selectedColorSchemes.map(({ id }) => id),
    viewports: selectedViewports.map(({ id, width, height }) => ({ id, width, height })),
    routes: selectedRoutes.map(({ id, path }) => ({ id, path })),
  },
  summary: {
    total: results.length,
    passed: results.filter(({ passed }) => passed).length,
    failed: results.filter(({ passed }) => !passed).length,
    screenshots: results.length,
    auditedTextNodes: results.reduce((sum, result) => sum + result.auditedTextCount, 0),
    imageBackedTextNodes: results.reduce((sum, result) => sum + result.imageBackedTextCount, 0),
    minimumContrastMargin: Math.min(...results.map(({ minimumContrastMargin }) => minimumContrastMargin ?? Infinity)),
  },
  results,
};
await writeFile(join(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);

const markdown = [
  '# NyankoFace theme matrix',
  '',
  `Result: **${manifest.summary.passed}/${manifest.summary.total} passed**  `,
  `Coverage: **${selectedThemes.length} themes × ${selectedColorSchemes.length} OS color schemes × ${selectedViewports.length} viewports × ${selectedRoutes.length} routes = ${results.length} screenshots**`,
  `Audited text nodes: **${manifest.summary.auditedTextNodes}** · Image-backed text reviewed visually: **${manifest.summary.imageBackedTextNodes}** · Minimum WCAG margin: **${manifest.summary.minimumContrastMargin}× required ratio**`,
  '',
  '| Result | Theme | OS scheme | Viewport | Route | Overflow | Contrast risks | Screenshot |',
  '|---|---|---|---|---|---:|---:|---|',
  ...results.map((result) => `| ${result.passed ? 'PASS' : 'FAIL'} | ${result.theme.label} | ${result.colorScheme.label} | ${result.viewport.id} | ${result.route.label} | ${result.horizontalOverflow}px | ${result.contrastRiskCount} | [view](${result.screenshot}) |`),
  '',
  '## Failures',
  '',
  ...results.filter(({ passed }) => !passed).flatMap((result) => [
    `### ${result.theme.label} / ${result.colorScheme.label} / ${result.viewport.id} / ${result.route.label}`,
    '',
    `- Defects: ${result.defects.join('; ')}`,
    `- Contrast evidence: ${result.contrastRisks.length ? `\`${JSON.stringify(result.contrastRisks)}\`` : 'none'}`,
    '',
    `![${result.theme.id} ${result.viewport.id} ${result.route.label}](${result.screenshot})`,
    '',
  ]),
];
await writeFile(join(outputDir, 'THEME_MATRIX.md'), `${markdown.join('\n')}\n`);
const contactSheets = await generateContactSheets({ manifest, outputDir });

process.stdout.write(`\nTheme matrix: ${selectedThemes.length} × ${selectedColorSchemes.length} × ${selectedViewports.length} × ${selectedRoutes.length} = ${results.length} screenshots\n`);
process.stdout.write(`Contact sheets: ${contactSheets.length}\n`);
process.stdout.write(`Report: ${join(outputDir, 'THEME_MATRIX.md')}\n`);
if (manifest.summary.failed > 0) process.exitCode = 1;
