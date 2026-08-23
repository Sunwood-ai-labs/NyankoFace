import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const repoPageSource = readFileSync(
  new URL('../app/[owner]/[repo]/page.tsx', import.meta.url),
  'utf8',
);
const detailTabsSource = readFileSync(
  new URL('../components/DetailTabs.tsx', import.meta.url),
  'utf8',
);
const repoSearchListSource = readFileSync(
  new URL('../components/RepoSearchList.tsx', import.meta.url),
  'utf8',
);
const repoCardSource = readFileSync(
  new URL('../components/RepoCard.tsx', import.meta.url),
  'utf8',
);
const globalStyles = readFileSync(
  new URL('../app/globals.css', import.meta.url),
  'utf8',
);

test('Space detail headers isolate shrinkable identity and runtime controls', () => {
  assert.match(repoPageSource, /nyankoface-space-header-main/);
  assert.match(repoPageSource, /nyankoface-space-header-identity/);
  assert.match(repoPageSource, /nyankoface-space-header-title/);
  assert.match(repoPageSource, /nyankoface-space-header-controls/);
  assert.match(repoPageSource, /nyankoface-space-detail-header/);
  assert.match(globalStyles, /\.nyankoface-space-header-main\s*\{[\s\S]*?min-width:\s*0;[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto;/);
  assert.match(globalStyles, /\.nyankoface-space-header-title\s*\{[\s\S]*?flex-wrap:\s*nowrap;[\s\S]*?overflow:\s*hidden;[\s\S]*?white-space:\s*nowrap;/);
  assert.match(globalStyles, /\.nyankoface-space-header-owner\s*\{[\s\S]*?text-overflow:\s*ellipsis;[\s\S]*?white-space:\s*nowrap;/);
  assert.match(globalStyles, /@media \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-detail-header > \.nyankoface-space-header-main[\s\S]*?flex-basis:\s*100%;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-header-identity\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*auto minmax\(0, 1fr\);/);
});

test('tablet Space apps size the runner from the wrapped header', () => {
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-app-page\s*\{[\s\S]*?display:\s*flex;[\s\S]*?height:\s*100vh;[\s\S]*?flex-direction:\s*column;/);
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-app-header\s*\{[\s\S]*?flex:\s*0 0 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-app-runner\s*\{[\s\S]*?display:\s*flex;[\s\S]*?min-height:\s*0;[\s\S]*?flex:\s*1 1 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-runner\s*\{[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-frame,[\s\S]*?\.nyankoface-space-stage,[\s\S]*?\.nyankoface-space-frame-stage\s*\{[\s\S]*?min-height:\s*0;[\s\S]*?flex:\s*1 1 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-app-header\s*\{[\s\S]*?min-height:\s*116px;/);
});

test('tablet Space app headers keep identity, controls, and tabs on readable rows', () => {
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-app-header > \.nyankoface-space-header-main\s*\{[\s\S]*?width:\s*100%;[\s\S]*?flex-basis:\s*100%;[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\);/);
  assert.match(globalStyles, /@media \(min-width: 641px\) and \(max-width: 1023px\)[\s\S]*?\.nyankoface-space-app-header > div:last-child\s*\{[\s\S]*?width:\s*100%;[\s\S]*?flex-basis:\s*100%;/);
});

test('mobile Space apps size the runner from the wrapped header', () => {
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-app-page\s*\{[\s\S]*?display:\s*flex;[\s\S]*?height:\s*100vh;[\s\S]*?flex-direction:\s*column;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-app-header\s*\{[\s\S]*?min-height:\s*116px;[\s\S]*?padding:\s*10px 16px 0;[\s\S]*?\}[\s\S]*?\.nyankoface-space-app-header\s*\{[\s\S]*?flex:\s*0 0 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-app-runner\s*\{[\s\S]*?display:\s*flex;[\s\S]*?min-height:\s*0;[\s\S]*?flex:\s*1 1 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-runner\s*\{[\s\S]*?min-height:\s*0;[\s\S]*?flex:\s*1 1 auto;[\s\S]*?height:\s*auto;/);
  assert.match(globalStyles, /@media \(max-width: 640px\)[\s\S]*?\.nyankoface-space-frame,[\s\S]*?\.nyankoface-space-stage,[\s\S]*?\.nyankoface-space-frame-stage\s*\{[\s\S]*?min-height:\s*0;[\s\S]*?flex:\s*1 1 auto;[\s\S]*?height:\s*auto;/);
  assert.doesNotMatch(globalStyles, /calc\(100vh - 133px\)/);
});

test('DetailTabs stays keyboard-reachable inside a bounded horizontal scroller', () => {
  assert.match(detailTabsSource, /min-w-0 max-w-full shrink-0 gap-1 overflow-x-auto/);
  assert.match(detailTabsSource, /whitespace-nowrap/);
  assert.match(detailTabsSource, /<Link[\s\S]*?href=\{cardHref\}/);
  assert.match(detailTabsSource, /<a href=\{filesHref\}/);
});

test('non-Space repository title keeps its existing responsive branch', () => {
  assert.match(repoPageSource, /isSpace \? 'nyankoface-space-header-main' : 'flex min-w-0 flex-1 items-center gap-2 py-3 max-sm:flex-wrap'/);
  assert.match(repoPageSource, /isSpaceApp \? 'max-sm:flex-nowrap max-sm:text-base' : 'max-sm:flex-nowrap'/);
  assert.match(repoPageSource, /isSpace \? 'nyankoface-space-header-repo truncate' : 'truncate'/);
  assert.match(repoPageSource, /title=\{`\$\{owner\}\/\$\{repoInfo\.name\}`\}/);
  assert.doesNotMatch(repoPageSource, /isSpaceApp \? 'truncate' : 'break-words'/);
});

test('repository cards can grow instead of clipping narrow content', () => {
  assert.match(repoSearchListSource, /min-w-0 rounded-lg border/);
  assert.match(repoSearchListSource, /min-h-\[62px\]/);
  assert.match(repoSearchListSource, /min-h-\[76px\]/);
  assert.doesNotMatch(repoSearchListSource, /(?:^|[\s'"])h-\[(?:62|76)px\]/);
  assert.match(repoCardSource, /min-w-0 min-h-44/);
  assert.match(repoCardSource, /max-w-\[42%\] truncate/);
  assert.match(repoCardSource, /min-w-0 flex-1 truncate/);
});
