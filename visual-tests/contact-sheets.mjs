import { mkdir, writeFile } from 'node:fs/promises';
import { join, relative, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

const escapeHtml = (value) => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;');

const chunksOf = (values, size) => {
  const chunks = [];
  for (let index = 0; index < values.length; index += size) chunks.push(values.slice(index, index + size));
  return chunks;
};

export async function generateContactSheets({ manifest, outputDir }) {
  const sheetsDir = join(outputDir, 'contact-sheets');
  await mkdir(sheetsDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const generated = [];

  try {
    for (const themeId of manifest.dimensions.themes) {
      for (const colorScheme of manifest.dimensions.colorSchemes || ['default']) {
        for (const viewport of manifest.dimensions.viewports) {
        const results = manifest.results.filter((result) =>
          result.theme.id === themeId && (result.colorScheme?.id || 'default') === colorScheme && result.viewport.id === viewport.id);
        const chunks = chunksOf(results, 9);
        for (let chunkIndex = 0; chunkIndex < chunks.length; chunkIndex += 1) {
          const chunk = chunks[chunkIndex];
          const sheetName = `${themeId}--${colorScheme}--${viewport.id}--${chunkIndex + 1}.png`;
          const sheetPath = join(sheetsDir, sheetName);
          const cards = chunk.map((result) => {
            const imageUrl = pathToFileURL(resolve(outputDir, result.screenshot)).href;
            return `
              <article class="card">
                <header><strong>${escapeHtml(result.route.label)}</strong><code>${escapeHtml(result.route.path)}</code></header>
                <div class="frame"><img src="${imageUrl}" alt="${escapeHtml(result.route.label)}"></div>
                <footer>${result.passed ? 'PASS' : 'FAIL'} · ${escapeHtml(result.route.focus || '')}</footer>
              </article>`;
          }).join('');
          const html = `<!doctype html><html><head><meta charset="utf-8"><style>
            *{box-sizing:border-box}html,body{margin:0;background:#0b1020;color:#ecf5ff;font:14px/1.35 Arial,sans-serif}
            body{padding:24px;width:1440px}.title{margin:0 0 6px;font-size:24px}.meta{margin:0 0 18px;color:#9eb2c8}
            .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;align-items:start}
            .card{overflow:hidden;border:1px solid #31415f;border-radius:12px;background:#121a2d;box-shadow:0 8px 24px #0005}
            header{display:flex;min-height:58px;flex-direction:column;gap:3px;padding:10px 12px;border-bottom:1px solid #31415f}
            header strong{font-size:15px}code{overflow:hidden;color:#78d9ed;text-overflow:ellipsis;white-space:nowrap}
            .frame{display:grid;height:640px;min-width:0;min-height:0;place-items:center;padding:8px;background:repeating-conic-gradient(#d9dee7 0 25%,#f4f6f9 0 50%) 50%/18px 18px}
            img{display:block;width:100%;height:100%;min-width:0;min-height:0;object-fit:contain;box-shadow:0 0 0 1px #172033}
            footer{min-height:42px;padding:10px 12px;color:#a9bad0;border-top:1px solid #31415f}
          </style></head><body>
            <h1 class="title">NyankoFace visual audit · ${escapeHtml(themeId)} · ${escapeHtml(colorScheme)} OS · ${escapeHtml(viewport.id)} · ${chunkIndex + 1}/${chunks.length}</h1>
            <p class="meta">Full-page screenshots scaled to fit. Open the source PNG for pixel-level review.</p>
            <main class="grid">${cards}</main>
          </body></html>`;
          const htmlPath = join(sheetsDir, '.contact-sheet.html');
          await writeFile(htmlPath, html);
          const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
          await page.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
          await page.waitForFunction(
            () => Array.from(document.images).every((image) => image.complete && image.naturalWidth > 0),
            null,
            { timeout: 60_000 },
          );
          await page.screenshot({ path: sheetPath, fullPage: true });
          await page.close();
          generated.push({
            theme: themeId,
            colorScheme,
            viewport: viewport.id,
            part: chunkIndex + 1,
            routes: chunk.map((result) => result.route.id),
            file: relative(outputDir, sheetPath).replaceAll('\\', '/'),
          });
        }
        }
      }
    }
  } finally {
    await browser.close();
  }

  const markdown = [
    '# NyankoFace screenshot contact sheets',
    '',
    `Coverage: **${manifest.summary.total} full-page screenshots** grouped into **${generated.length} review sheets**.`,
    '',
    '| Theme | OS scheme | Viewport | Part | Routes | Sheet |',
    '|---|---|---|---:|---|---|',
    ...generated.map((sheet) =>
      `| ${sheet.theme} | ${sheet.colorScheme} | ${sheet.viewport} | ${sheet.part} | ${sheet.routes.join(', ')} | [open](${sheet.file}) |`),
    '',
  ];
  await writeFile(join(outputDir, 'CONTACT_SHEETS.md'), `${markdown.join('\n')}\n`);
  return generated;
}
