import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const repositoryUrl =
  process.env.README_REPOSITORY_URL ??
  'https://github.com/Sunwood-ai-labs/NyankoFace';
const outputDirectory = path.resolve(
  process.cwd(),
  process.env.README_AUDIT_OUTPUT ?? '../docs/evidence/readme-layout',
);
const maximumPortraitHeight = Number(
  process.env.README_MAX_PORTRAIT_HEIGHT ?? 420,
);

const targets = [
  { id: 'english', url: repositoryUrl },
  { id: 'japanese', url: `${repositoryUrl}/blob/main/README.ja.md` },
];

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});
const results = [];

try {
  for (const target of targets) {
    const page = await context.newPage();
    await page.goto(target.url, { waitUntil: 'domcontentloaded' });
    await page.locator('article').waitFor();

    const audit = await page.locator('article').evaluate(
      (article, maxHeight) => {
        const images = [...article.querySelectorAll('img')].map((image) => {
          const rect = image.getBoundingClientRect();
          return {
            alt: image.alt,
            src: image.getAttribute('src'),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            ratio:
              rect.width > 0
                ? Number((rect.height / rect.width).toFixed(2))
                : 0,
            visible: image.checkVisibility({
              checkOpacity: true,
              checkVisibilityCSS: true,
            }),
          };
        });

        return {
          articleWidth: Math.round(article.getBoundingClientRect().width),
          pageScrollWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
          visibleImages: images.filter((image) => image.visible).length,
          collapsedEvidence: [...article.querySelectorAll('details')]
            .filter((details) => !details.open)
            .map((details) => details.querySelector('summary')?.textContent?.trim())
            .filter(Boolean),
          oversizedPortraits: images.filter(
            (image) =>
              image.visible &&
              image.height > maxHeight &&
              image.ratio > 1.1,
          ),
        };
      },
      maximumPortraitHeight,
    );

    results.push({ id: target.id, url: page.url(), ...audit });
    await page.close();
  }
} finally {
  await browser.close();
}

const report = {
  viewport: { width: 1440, height: 1000 },
  maximumPortraitHeight,
  results,
};

await writeFile(
  path.join(outputDirectory, 'latest-audit.json'),
  `${JSON.stringify(report, null, 2)}\n`,
  'utf8',
);

console.log(JSON.stringify(report, null, 2));

const failures = results.flatMap((result) =>
  result.oversizedPortraits.map((image) => ({
    readme: result.id,
    ...image,
  })),
);

if (failures.length > 0) {
  console.error(
    `README layout audit failed: ${failures.length} oversized portrait image(s).`,
  );
  process.exitCode = 1;
}
