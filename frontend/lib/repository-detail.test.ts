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

test('repository detail resolves a case-insensitive root README and distinguishes load states', () => {
  assert.match(repoPageSource, /loadRepositoryReadme\(owner, repo, ref\)/);
  assert.match(repoPageSource, /REPOSITORY_README_CACHE_TTL_MS/);
  assert.match(repoPageSource, /repositoryReadmeCache/);
  assert.match(repoPageSource, /candidate\.name\.toLowerCase\(\) === 'readme\.md'/);
  assert.match(repoPageSource, /status: 'absent'/);
  assert.match(repoPageSource, /status: 'unavailable'/);
  assert.match(repoPageSource, /status: 'too-large'/);
  assert.match(repoPageSource, /status: 'present'/);
  assert.match(repoPageSource, /readmeStatus = 'empty'/);
  assert.match(repoPageSource, /readmeStatus = 'parse'/);
  assert.match(repoPageSource, /README\.md is too large to preview/);
  assert.match(repoPageSource, /README\.md could not be loaded/);
  assert.match(repoPageSource, /README\.md could not be parsed as Markdown/);
  assert.match(repoPageSource, /tab=files&revision=\$\{encodeURIComponent\(revision\)\}/);
  assert.match(repoPageSource, /getContents\(owner, repo, path, ref\)/);
  assert.match(repoPageSource, /refKind = revision \? 'tag'/);
});

test('untyped repositories keep repository labels and avoid model-only actions', () => {
  assert.match(repoPageSource, /kind === null \? ui\(locale, 'リポジトリ', 'Repository'\)/);
  assert.match(repoPageSource, /kind === null \? `\/git\/\$\{owner\}` : '\/models'/);
  assert.match(repoPageSource, /kind === null \? ui\(locale, 'リポジトリの操作', 'Repository actions'\)/);
  assert.match(repoPageSource, /kind === null \? \(/);
  assert.match(repoPageSource, /ui\(locale, 'ファイルを見る', 'Browse files'\)/);
  assert.match(repoPageSource, /ui\(locale, 'リポジトリを開く', 'Open repository'\)/);
  assert.match(detailTabsSource, /kind == null[\s\S]*?ui\(locale, 'リポジトリ', 'Repository'\)/);
  assert.match(detailTabsSource, /kind == null \? 'folder' : 'file'/);
  assert.match(detailTabsSource, /ui\(locale, 'モデルカード', 'Model card'\)/);
});

test('README, blob previews, Docs, and Knowledge all stay on parseReadme', () => {
  const sharedMarkdownSurfaces = [
    '../app/[owner]/[repo]/page.tsx',
    '../app/[owner]/[repo]/blob/[...path]/page.tsx',
    '../app/docs/[owner]/[slug]/page.tsx',
    './knowledge.ts',
  ];
  for (const surface of sharedMarkdownSurfaces) {
    const source = readFileSync(new URL(surface, import.meta.url), 'utf8');
    assert.match(source, /parseReadme/, surface);
  }
});
