import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const outputDir = dirname(fileURLToPath(import.meta.url));
const candidatesDir = join(outputDir, 'candidates');

const palette = {
  light: { bg: '#f8fafc', ink: '#102a43', accent: '#06b6d4', warm: '#f59e0b' },
  dark: { bg: '#0b1220', ink: '#f8fafc', accent: '#67e8f9', warm: '#fbbf24' },
  mono: { bg: '#ffffff', ink: '#111827', accent: '#111827', warm: '#111827' },
  inverted: { bg: '#111827', ink: '#ffffff', accent: '#ffffff', warm: '#ffffff' },
};

const candidates = [
  { id: '01', name: 'NyankoFace Signal Wordmark', short: 'open face + signal', shortlist: 'PRIMARY' },
  { id: '02', name: 'Open Eye', short: 'soft lowercase + eye', shortlist: '' },
  { id: '03', name: 'Neural Horizontal Face', short: 'layered face lines', shortlist: '' },
  { id: '04', name: 'OF Brain-Line Monogram', short: 'OF + neural stroke', shortlist: '' },
  { id: '05', name: 'Open Portal Wordmark', short: 'repository portal', shortlist: '' },
  { id: '06', name: 'Cat Signal', short: 'cat continuity route', shortlist: 'CONTINUITY' },
  { id: '07', name: 'Face Aperture', short: 'open / close motion', shortlist: '' },
  { id: '08', name: 'Community Wave', short: 'people + repositories', shortlist: '' },
  { id: '09', name: 'Black Wordmark + Cyan Cut', short: 'minimal cyan cut', shortlist: 'UTILITY' },
  { id: '10', name: 'Mark-First Monogram System', short: 'responsive mark system', shortlist: '' },
];

function xml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function stroke(color, width = 16) {
  return `fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"`;
}

function mark(index, colors) {
  const s = stroke(colors.ink);
  const a = stroke(colors.accent);
  switch (index) {
    case 1:
      return `<g ${s}>
        <path d="M42 76h126"/><path d="M42 128h172"/><path d="M42 180h126"/>
        <path d="M182 76h32" stroke="${colors.accent}"/><path d="M42 128h38" stroke="${colors.warm}"/>
      </g>`;
    case 2:
      return `<g ${s}>
        <path d="M32 128c26-48 71-68 112-68 34 0 61 15 80 38"/>
        <path d="M32 128c26 48 71 68 112 68 34 0 61-15 80-38"/>
        <circle cx="116" cy="128" r="20" fill="${colors.accent}" stroke="none"/><circle cx="116" cy="128" r="7" fill="${colors.bg}" stroke="none"/>
      </g>`;
    case 3:
      return `<g ${s}>
        <path d="M36 72h184"/><path d="M52 128h152"/><path d="M70 184h116"/>
        <circle cx="92" cy="128" r="8" fill="${colors.accent}" stroke="none"/><circle cx="164" cy="128" r="8" fill="${colors.accent}" stroke="none"/>
        <path d="M104 168q24 16 48 0" stroke="${colors.warm}"/>
      </g>`;
    case 4:
      return `<g ${s}>
        <circle cx="86" cy="128" r="60"/><path d="M146 68v120"/>
        <path d="M146 74h70M146 128h55M146 182h70" stroke="${colors.accent}"/>
        <path d="M74 104h24" stroke="${colors.warm}"/>
      </g>`;
    case 5:
      return `<g ${s}>
        <path d="M86 50H46v156h40M170 50h40v156h-40"/>
        <path d="M78 96h100M78 128h70M78 160h100" stroke="${colors.accent}"/>
        <path d="M154 128h24" stroke="${colors.warm}"/>
      </g>`;
    case 6:
      return `<g ${s}>
        <path d="M54 104V52l48 34 26-16 26 16 48-34v52"/>
        <path d="M54 104c0 70 32 106 74 106s74-36 74-106"/>
        <circle cx="98" cy="132" r="9" fill="${colors.accent}" stroke="none"/><circle cx="158" cy="132" r="9" fill="${colors.accent}" stroke="none"/>
        <path d="M110 166q18 12 36 0" stroke="${colors.warm}"/>
      </g>`;
    case 7:
      return `<g ${s}>
        <path d="M38 86h180"/><path d="M38 170h180"/>
        <path d="M78 128h100" stroke="${colors.accent}" stroke-width="28"/>
        <circle cx="128" cy="128" r="14" fill="${colors.bg}" stroke="none"/>
        <path d="M106 128h44" stroke="${colors.warm}"/>
      </g>`;
    case 8:
      return `<g ${a}>
        <path d="M24 96c28-24 56-24 84 0s56 24 84 0 36-24 40-20"/>
        <path d="M24 128c28-24 56-24 84 0s56 24 84 0 36-24 40-20"/>
        <path d="M24 160c28-24 56-24 84 0s56 24 84 0 36-24 40-20"/>
      </g><circle cx="128" cy="128" r="17" fill="${colors.warm}"/>`;
    case 9:
      return `<g ${s}>
        <path d="M92 56c-40 0-66 28-66 72s26 72 66 72c22 0 38-8 50-22"/>
        <path d="M112 72h98M112 128h72M112 184h98"/>
        <path d="M72 128h38" stroke="${colors.accent}" stroke-width="26"/>
      </g>`;
    default:
      return `<g ${s}>
        <rect x="42" y="42" width="172" height="172" rx="42"/>
        <path d="M42 102h58M156 102h58M42 154h58M156 154h58" stroke="${colors.accent}"/>
        <circle cx="128" cy="128" r="20" fill="${colors.warm}" stroke="none"/>
      </g>`;
  }
}

function defs() {
  return `<defs>
    <linearGradient id="hero" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#12263f"/><stop offset="1" stop-color="#0b1220"/></linearGradient>
    <linearGradient id="card" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#ffffff"/><stop offset="1" stop-color="#e9f4f7"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#020617" flood-opacity=".18"/></filter>
  </defs>`;
}

function text(value, x, y, size, fill, weight = 400, anchor = 'start') {
  return `<text x="${x}" y="${y}" fill="${fill}" font-family="Inter,Segoe UI,sans-serif" font-size="${size}px" font-weight="${weight}" text-anchor="${anchor}">${xml(value)}</text>`;
}

function board() {
  const width = 1920;
  const height = 1320;
  const cardWidth = 344;
  const cardHeight = 470;
  const gap = 22;
  const left = 72;
  const top = 205;
  let cards = '';
  for (let i = 0; i < candidates.length; i += 1) {
    const item = candidates[i];
    const x = left + (i % 5) * (cardWidth + gap);
    const y = top + Math.floor(i / 5) * (cardHeight + gap);
    const badge = item.shortlist
      ? `<rect x="${x + 238}" y="${y + 22}" width="84" height="25" rx="12" fill="#0e7490"/><text x="${x + 280}" y="${y + 39}" fill="#ffffff" font-family="Inter,Segoe UI,sans-serif" font-size="11px" font-weight="700" text-anchor="middle">${xml(item.shortlist)}</text>`
      : '';
    cards += `<g filter="url(#shadow)">
      <rect x="${x}" y="${y}" width="${cardWidth}" height="${cardHeight}" rx="26" fill="url(#card)"/>
      <rect x="${x}" y="${y}" width="8" height="${cardHeight}" rx="4" fill="${item.shortlist ? '#06b6d4' : '#f59e0b'}"/>
      ${text(item.id, x + 24, y + 43, 16, '#64748b', 800)}
      ${text(item.name, x + 24, y + 75, 17, '#102a43', 800)}
      ${badge}
      <rect x="${x + 24}" y="${y + 100}" width="142" height="142" rx="20" fill="#f8fafc" stroke="#dbe7ed"/>
      <g transform="translate(${x + 31} ${y + 107}) scale(.50)">${mark(i + 1, palette.light)}</g>
      <rect x="${x + 184}" y="${y + 100}" width="136" height="142" rx="20" fill="#0b1220" stroke="#20334c"/>
      <g transform="translate(${x + 191} ${y + 107}) scale(.50)">${mark(i + 1, palette.dark)}</g>
      ${text(item.short, x + 24, y + 286, 14, '#0e7490', 700)}
      ${text('24 / 32 px', x + 24, y + 316, 13, '#475569', 600)}
      ${text(item.shortlist ? 'shortlist candidate' : 'exploration candidate', x + 24, y + 350, 12, '#64748b', 500)}
      <line x1="${x + 24}" x2="${x + 320}" y1="${y + 378}" y2="${y + 378}" stroke="#dbe7ed"/>
      ${text('light  ·  dark  ·  mono  ·  inverse', x + 24, y + 410, 11, '#64748b', 500)}
      <circle cx="${x + 284}" cy="${y + 404}" r="7" fill="#06b6d4"/><circle cx="${x + 304}" cy="${y + 404}" r="7" fill="#f59e0b"/>
    </g>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="brand-exploration-title brand-exploration-desc">
    <title id="brand-exploration-title">NyankoFace brand exploration</title>
    <desc id="brand-exploration-desc">Ten deterministic NyankoFace logo directions with a provisional shortlist.</desc>
    ${defs()}
    <rect width="${width}" height="${height}" fill="#07111f"/>
    <rect x="0" y="0" width="${width}" height="175" fill="url(#hero)"/>
    ${text('NYANKOFACE BRAND EXPLORATION', 72, 68, 24, '#67e8f9', 800)}
    ${text('10 directions · initial shortlist · deterministic SVG study', 72, 116, 42, '#ffffff', 800)}
    ${text('Reference language: high-contrast icon + wordmark, translated into NyankoFace signal / face / community meaning.', 72, 151, 16, '#a8c1d6', 500)}
    <rect x="1510" y="58" width="318" height="72" rx="18" fill="#102a43" stroke="#2b4a63"/>
    ${text('PROVISIONAL SHORTLIST', 1538, 87, 12, '#fbbf24', 800)}
    ${text('01  ·  06  ·  09', 1538, 116, 23, '#ffffff', 800)}
    ${cards}
    <rect x="72" y="1192" width="1776" height="76" rx="22" fill="#102a43"/>
    ${text('Decision frame', 102, 1224, 13, '#67e8f9', 800)}
    ${text('24px recognition · single-color export · light/dark contrast · continuity · distinctiveness · system expansion', 102, 1251, 16, '#e4f0f7', 600)}
    ${text('NYANKOFACE', 1810, 1240, 14, '#fbbf24', 800, 'end')}
  </svg>`;
}

function variantBoard() {
  const width = 1920;
  const rowHeight = 112;
  const height = 190 + rowHeight * candidates.length + 56;
  const columns = [
    ['24 / light', 'light'], ['24 / dark', 'dark'], ['32 / light', 'light'],
    ['32 / dark', 'dark'], ['24 / mono', 'mono'], ['24 / inverse', 'inverted'],
  ];
  const nameX = 70;
  const startX = 505;
  const cellWidth = 222;
  let rows = '';
  for (let i = 0; i < candidates.length; i += 1) {
    const item = candidates[i];
    const y = 150 + i * rowHeight;
    rows += `<rect x="48" y="${y}" width="1824" height="92" rx="18" fill="${i % 2 === 0 ? '#f8fafc' : '#e8f1f5'}"/>
      ${text(`${item.id}  ${item.name}`, nameX, y + 39, 16, '#102a43', 800)}
      ${item.shortlist ? `<rect x="${nameX}" y="${y + 54}" width="86" height="21" rx="10" fill="#0e7490"/>${text(item.shortlist, nameX + 43, y + 69, 10, '#ffffff', 800, 'middle')}` : text(item.short, nameX, y + 69, 11, '#64748b', 600)}
      ${columns.map(([, variant], column) => {
        const cellX = startX + column * cellWidth;
        const size = column < 2 || column >= 4 ? 24 / 256 : 32 / 256;
        const surface = 256 * size;
        const offsetX = (190 - surface) / 2;
        const offsetY = (72 - surface) / 2;
        return `<rect x="${cellX}" y="${y + 10}" width="190" height="72" rx="14" fill="${palette[variant].bg}" stroke="#cad9e1"/><g transform="translate(${cellX + offsetX} ${y + 10 + offsetY}) scale(${size})">${mark(i + 1, palette[variant])}</g>`;
      }).join('')}`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="variant-matrix-title variant-matrix-desc">
    <title id="variant-matrix-title">NyankoFace shrink and color matrix</title>
    <desc id="variant-matrix-desc">Ten logo directions compared at true 24 and 32 pixel surface sizes across light, dark, monochrome, and inverse variants.</desc>
    ${defs()}
    <rect width="${width}" height="${height}" fill="#07111f"/>
    ${text('SHRINK + COLOR MATRIX', 70, 62, 24, '#67e8f9', 800)}
    ${text('Every direction is checked as a mark, not only as a large illustration.', 70, 103, 28, '#ffffff', 800)}
    ${columns.map(([label], i) => text(label, startX + i * cellWidth + 95, 137, 12, '#a8c1d6', 700, 'middle')).join('')}
    ${rows}
    <rect x="48" y="${height - 44}" width="1824" height="24" rx="12" fill="#102a43"/>
    ${text('Pass target: recognizable silhouette at 24px, clean 1-color export, no thin strokes that collapse on favicon or navbar surfaces.', 70, height - 27, 12, '#d7e6ef', 600)}
  </svg>`;
}

function standalone(item, index) {
  const colors = palette.light;
  const titleId = `candidate-${item.id}-title`;
  const descId = `candidate-${item.id}-desc`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-labelledby="${titleId} ${descId}">
    <title id="${titleId}">${xml(item.name)}</title><desc id="${descId}">NyankoFace brand exploration candidate ${xml(item.id)}.</desc>
    <g>${mark(index, colors)}</g>
  </svg>`;
}

await mkdir(candidatesDir, { recursive: true });
const cleanSvg = (value) => value.replace(/[ \t]+$/gm, '');
await writeFile(join(outputDir, 'brand-exploration.svg'), cleanSvg(board()), 'utf8');
await writeFile(join(outputDir, 'variant-matrix.svg'), cleanSvg(variantBoard()), 'utf8');
for (let i = 0; i < candidates.length; i += 1) {
  const item = candidates[i];
  await writeFile(join(candidatesDir, `${item.id}-${item.name.toLowerCase().replaceAll(/[^a-z0-9]+/g, '-')}.svg`), standalone(item, i + 1), 'utf8');
}

process.stdout.write(`Generated ${candidates.length} candidate SVGs and two comparison boards in ${resolve(outputDir)}\n`);
