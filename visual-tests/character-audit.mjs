import { chromium } from 'playwright';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const baseUrl = (process.env.VISUAL_QA_BASE_URL || 'https://localhost:8443').replace(/\/$/, '');
const outputDir = resolve(process.env.CHARACTER_QA_OUTPUT_DIR || join(root, 'artifacts', 'characters'));
const themes = ['standard', 'solarpunk', 'cyberpunk'];
const viewports = [
  { id: 'desktop', width: 1440, height: 1000 },
  { id: 'mobile', width: 390, height: 844 },
];
const routes = [
  {
    id: 'directory',
    path: '/characters',
    required: [
      'Ayano Yukimura',
      'Fuhyo',
      'Hisha',
      'Kakugyo',
      'Kohaku',
      'Maki',
      'Momiji',
      'Onizuka',
      'PuruPuru · 30 states',
      'PuruPuru · 6 states',
    ],
    imageMinimum: 18,
    petCards: ['ayano-yukimura-codex-pet', 'fuhyo-codex-pet', 'hisha-codex-pet', 'kakugyo-codex-pet', 'kohaku-codex-pet', 'maki-codex-pet', 'momiji-codex-pet', 'onizuka-codex-pet'],
    hrefs: [
      '/nyankoface/momiji-codex-pet',
      '/nyankoface/momiji-character-sheet',
    ],
    forbiddenHrefs: [
      '/nyankoface/character-design-images',
      '/nyankoface/character-design-images?pet=momiji',
    ],
    animatedPreview: true,
  },
  {
    id: 'purupuru-upper',
    path: '/nyankoface/lumi-jelly-pngtuber',
    required: ['PuruPuru', '6状態', 'avatar/default-settings.json'],
    hrefs: ['/git/nyankoface/lumi-jelly-pngtuber/src/branch/main/avatar/default-settings.json'],
    animatedPreview: true,
  },
  {
    id: 'purupuru-head-motion',
    path: '/nyankoface/lumi-jelly-head-motion-pngtuber',
    required: ['PuruPuru', '5方向・30状態', 'PuruPuru direction-control patch'],
    hrefs: ['/git/nyankoface/lumi-jelly-head-motion-pngtuber/src/branch/main/integration/purupuru-lumi-jelly-head-motion.patch.gz'],
    animatedPreview: true,
    directionControl: true,
  },
  {
    id: 'codex-pet-momiji',
    path: '/nyankoface/momiji-codex-pet',
    required: ['Momiji · Codex Pet', '独立パッケージ', 'pet.json', 'spritesheet.webp'],
    hrefs: [
      '/git/nyankoface/momiji-codex-pet/src/branch/main/pet.json',
      '/git/nyankoface/momiji-codex-pet/src/branch/main/spritesheet.webp',
    ],
  },
  {
    id: 'character-sheet-momiji',
    path: '/nyankoface/momiji-character-sheet',
    required: ['キャラクターシート', '独立リポジトリ', 'metadata/characters.csv'],
    hrefs: [
      '/git/nyankoface/momiji-character-sheet/src/branch/main/metadata/characters.csv',
    ],
  },
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(join(outputDir, 'screenshots'), { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

for (const theme of themes) {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport,
      ignoreHTTPSErrors: true,
      colorScheme: theme === 'cyberpunk' ? 'dark' : 'light',
      reducedMotion: 'no-preference',
    });
    await context.addInitScript((selectedTheme) => {
      localStorage.setItem('nyankoface-theme-v2', selectedTheme);
      document.cookie = `nyankoface-theme=${selectedTheme}; Path=/; Max-Age=31536000; SameSite=Lax`;
    }, theme);

    for (const route of routes) {
      const page = await context.newPage();
      const consoleErrors = [];
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      });
      const response = await page.goto(`${baseUrl}${route.path}`, { waitUntil: 'networkidle', timeout: 45_000 });
      await page.evaluate(() => document.fonts?.ready).catch(() => undefined);
      const previewBefore = route.animatedPreview
        ? await (async () => {
            await page.locator('[data-purupuru-preview]').first().waitFor({ state: 'visible' });
            await page.waitForFunction(
              () => document.querySelector('[data-purupuru-preview]')?.getAttribute('data-frames-ready') === 'true',
              undefined,
              { timeout: 15_000 },
            );
            return page.locator('[data-purupuru-preview]').first().getAttribute('data-frame-path');
          })()
        : null;
      let alphaBlend = null;
      let minimumCoverage = null;
      let alphaBlendScreenshot = null;
      if (route.animatedPreview) {
        await page.waitForFunction(
          (initialFrame) => document.querySelector('[data-purupuru-preview]')?.getAttribute('data-frame-path') !== initialFrame,
          previewBefore,
          { timeout: 2_000 },
        );
        await page.waitForTimeout(90);
        alphaBlend = await page.locator('[data-purupuru-preview]').first().evaluate((preview) => {
          const previous = preview.querySelector('[data-purupuru-layer="previous"]');
          const current = preview.querySelector('[data-purupuru-layer="current"]');
          return {
            active: preview.getAttribute('data-blend-active') === 'true',
            layers: Number(Boolean(previous)) + Number(Boolean(current)),
            previousOpacity: previous ? Number.parseFloat(getComputedStyle(previous).opacity) : null,
            currentOpacity: current ? Number.parseFloat(getComputedStyle(current).opacity) : null,
          };
        });
        minimumCoverage = await page.locator('[data-purupuru-preview]').first().evaluate(async (preview) => {
          let minimum = 1;
          const started = performance.now();
          while (performance.now() - started < 1_200) {
            const previous = preview.querySelector('[data-purupuru-layer="previous"]');
            const current = preview.querySelector('[data-purupuru-layer="current"]');
            const previousOpacity = previous ? Number.parseFloat(getComputedStyle(previous).opacity) : 0;
            const currentOpacity = current ? Number.parseFloat(getComputedStyle(current).opacity) : 0;
            // Incoming alpha is composited over a fully opaque outgoing frame.
            const compositeCoverage = previous
              ? 1 - ((1 - previousOpacity) * (1 - currentOpacity))
              : currentOpacity;
            minimum = Math.min(minimum, compositeCoverage);
            await new Promise((resolve) => requestAnimationFrame(resolve));
          }
          return minimum;
        });
        alphaBlendScreenshot = join(
          outputDir,
          'screenshots',
          `${theme}-${viewport.id}-${route.id}-alpha-blend.png`,
        );
        await page.locator('[data-purupuru-preview]').first().screenshot({ path: alphaBlendScreenshot });
      }
      const previewAfter = route.animatedPreview
        ? await page.locator('[data-purupuru-preview]').first().getAttribute('data-frame-path')
        : null;
      if (route.animatedPreview) await page.waitForTimeout(320);
      let directionChanged = null;
      if (route.directionControl) {
        const directionButton = page.locator('[data-purupuru-direction="right"]');
        await directionButton.click();
        directionChanged = await page.locator('[data-purupuru-preview]').first().getAttribute('data-direction');
      }
      if (route.animatedPreview) {
        const pauseButton = page.locator('[data-purupuru-toggle]');
        if (await pauseButton.count()) await pauseButton.first().click();
      }
      await page.evaluate(async () => {
        const step = Math.max(480, Math.floor(window.innerHeight * 0.7));
        for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
          window.scrollTo(0, y);
          await new Promise((resolve) => window.setTimeout(resolve, 80));
        }
        window.scrollTo(0, 0);
      });
      await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete), undefined, { timeout: 15_000 }).catch(() => undefined);
      const state = await page.evaluate(() => ({
        theme: document.documentElement.getAttribute('data-nyankoface-theme') || 'standard',
        text: document.body.innerText,
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        images: Array.from(document.images).map((image) => ({
          alt: image.alt,
          complete: image.complete,
          naturalWidth: image.naturalWidth,
        })),
        links: Array.from(document.querySelectorAll('a[href]')).map((link) => link.getAttribute('href')),
        petCards: Array.from(document.querySelectorAll('[data-codex-pet-card]')).map((card) => card.getAttribute('data-codex-pet-card')),
      }));
      const missingText = route.required.filter((text) => !state.text.includes(text));
      const missingLinks = (route.hrefs || []).filter((href) => !state.links.includes(href));
      const forbiddenLinks = (route.forbiddenHrefs || []).filter((href) => state.links.includes(href));
      const characterImages = state.images.filter((image) => /preview|プレビュー/i.test(image.alt));
      const brokenImages = characterImages.filter((image) => !image.complete || image.naturalWidth < 1);
      const screenshot = join(outputDir, 'screenshots', `${theme}-${viewport.id}-${route.id}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      results.push({
        theme,
        viewport: viewport.id,
        route: route.id,
        status: response?.status() || 0,
        activeTheme: state.theme,
        missingText,
        missingLinks,
        forbiddenLinks,
        characterImages: characterImages.length,
        brokenImages,
        horizontalOverflow: Math.max(0, state.scrollWidth - state.clientWidth),
        consoleErrors,
        petCards: state.petCards,
        animationChanged: route.animatedPreview ? previewBefore !== previewAfter : null,
        alphaBlend,
        minimumCoverage,
        alphaBlendScreenshot,
        directionChanged,
        screenshot,
        passed:
          response?.status() === 200
          && state.theme === theme
          && missingText.length === 0
          && missingLinks.length === 0
          && forbiddenLinks.length === 0
          && brokenImages.length === 0
          && characterImages.length >= (route.imageMinimum || 1)
          && (!route.petCards || route.petCards.every((id) => state.petCards.includes(id)))
          && (!route.animatedPreview || previewBefore !== previewAfter)
          && (!route.animatedPreview || (
            alphaBlend?.active
            && alphaBlend.layers === 2
            && alphaBlend.previousOpacity > 0.05
            && alphaBlend.currentOpacity > 0.05
          ))
          && (!route.animatedPreview || minimumCoverage >= 0.995)
          && (!route.directionControl || directionChanged === 'right')
          && state.scrollWidth - state.clientWidth <= 1
          && consoleErrors.length === 0,
      });
      await page.close();
    }
    await context.close();
  }
}

await browser.close();
const failures = results.filter((result) => !result.passed);
const report = { generatedAt: new Date().toISOString(), baseUrl, cases: results.length, failures, results };
await writeFile(join(outputDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
await writeFile(join(outputDir, 'README.md'), [
  '# Character format visual audit',
  '',
  `- Coverage: ${themes.length} themes × ${viewports.length} viewports × ${routes.length} routes = ${results.length} screenshots`,
  `- Result: ${failures.length === 0 ? 'PASS' : 'FAIL'} (${results.length - failures.length}/${results.length})`,
  '- Checks: eight independent Codex Pet repositories, independent character-sheet links, no legacy query-param cards, decoded PuruPuru frames, real frame changes, two-layer alpha blends with no background exposure, direction controls, active theme, console errors, and horizontal overflow.',
  '',
].join('\n'));
console.log(JSON.stringify({ outputDir, cases: results.length, failures: failures.length }, null, 2));
if (failures.length) {
  console.error(JSON.stringify({ characterAuditFailures: failures }, null, 2));
}
if (failures.length) process.exitCode = 1;
