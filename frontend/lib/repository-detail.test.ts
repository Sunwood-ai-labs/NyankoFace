import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { encodeRepositoryPath, forgejoCommitsUrl, forgejoRawUrl, forgejoTreeUrl } from './forgejo';

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
  assert.match(repoPageSource, /candidate\.type === 'file' \|\| candidate\.type === 'symlink'/);
  assert.match(repoPageSource, /resolveRepositorySymlinkPath\(readmePath, currentEntry\.target\)/);
  assert.match(repoPageSource, /getContentMetadata\(owner, repo, targetPath, ref\)/);
  assert.match(repoPageSource, /const targetMetadata = await getContentMetadata/);
  assert.match(repoPageSource, /target\.startsWith\('\/'\)/);
  assert.match(repoPageSource, /normalizeRepositoryPath/);
  assert.doesNotMatch(repoPageSource, /const trimmed = value\.trim\(\)/);
  assert.match(repoPageSource, /REPOSITORY_README_CACHE_TTL_MS/);
  assert.match(repoPageSource, /MAX_REPOSITORY_README_CACHE_ENTRIES/);
  assert.match(repoPageSource, /MAX_README_SYMLINK_DEPTH/);
  assert.match(repoPageSource, /visitedReadmePaths/);
  assert.match(repoPageSource, /currentEntry\.type !== 'symlink'/);
  assert.match(repoPageSource, /repositoryReadmeCache/);
  assert.match(repoPageSource, /pruneRepositoryReadmeCache/);
  assert.match(repoPageSource, /candidate\.name\.toLowerCase\(\) === 'readme\.md'/);
  assert.match(repoPageSource, /readmeEntries\.find\(\(candidate\) => candidate\.name === 'README\.md'\) \|\| readmeEntries\[0\]/);
  assert.match(repoPageSource, /status: 'absent'/);
  assert.match(repoPageSource, /status: 'unavailable'/);
  assert.match(repoPageSource, /status: 'too-large'/);
  assert.match(repoPageSource, /status: 'present'/);
  assert.match(repoPageSource, /const rawBuffer = Buffer\.from/);
  assert.match(repoPageSource, /rawBuffer\.byteLength >= MAX_README_PREVIEW_BYTES/);
  assert.match(repoPageSource, /readmeStatus = 'empty'/);
  assert.match(repoPageSource, /readmeStatus = 'parse'/);
  assert.match(repoPageSource, /README\.md is too large to preview/);
  assert.match(repoPageSource, /README\.md could not be loaded/);
  assert.match(repoPageSource, /README\.md could not be parsed as Markdown/);
  assert.match(repoPageSource, /tab=files&revision=\$\{encodeURIComponent\(revision\)\}/);
  assert.match(repoPageSource, /getContents\(owner, repo, path, ref\)/);
  assert.match(repoPageSource, /refKind = revision \? 'tag'/);
  assert.match(repoPageSource, /const readmeDirectory = !taggedPromptRaw/);
  assert.match(repoPageSource, /encodeRepositoryPath\(readmeAssetPath\)/);
  assert.match(repoPageSource, /forgejoRawUrl\(owner, repo, readmeAssetPath, ref, refKind\)/);
  assert.match(repoPageSource, /forgejoTreeUrl\(owner, repo, readmeDirectory, revision, 'tag'\)/);
  assert.match(repoPageSource, /blob\/\$\{readmeUrlAssetPath\}/);
});

test('encodes slash-bearing branch and tag names in Forgejo navigation URLs', () => {
  const ref = 'release/candidate 1#2?final';

  assert.equal(
    forgejoTreeUrl('owner', 'repo', 'docs/guide.md', ref),
    '/git/owner/repo/src/branch/release%2Fcandidate%201%232%3Ffinal/docs/guide.md',
  );
  assert.equal(
    forgejoTreeUrl('owner', 'repo', 'docs#v1/README.md'),
    '/git/owner/repo/src/branch/main/docs%23v1/README.md',
  );
  assert.equal(
    forgejoRawUrl('owner', 'repo', 'README.md', ref, 'tag'),
    '/git/owner/repo/raw/tag/release%2Fcandidate%201%232%3Ffinal/README.md',
  );
  assert.equal(
    forgejoRawUrl('owner', 'repo', 'docs#v1/README.md'),
    '/git/owner/repo/raw/branch/main/docs%23v1/README.md',
  );
  assert.equal(
    forgejoCommitsUrl('owner', 'repo', '', ref, 'tag'),
    '/git/owner/repo/commits/tag/release%2Fcandidate%201%232%3Ffinal',
  );
  assert.equal(
    forgejoCommitsUrl('owner', 'repo', 'docs#v1/README.md'),
    '/git/owner/repo/commits/branch/main/docs%23v1/README.md',
  );
});

test('encodes reserved characters in Forgejo repository paths by segment', () => {
  assert.equal(encodeRepositoryPath('docs#v1/README.md'), 'docs%23v1/README.md');
  assert.equal(encodeRepositoryPath('docs?draft/README.md'), 'docs%3Fdraft/README.md');
  assert.equal(encodeRepositoryPath('/docs/space name/README.md'), 'docs/space%20name/README.md');
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
