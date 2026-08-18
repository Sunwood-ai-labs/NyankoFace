import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const blobPage = readFileSync(
  new URL('../app/[owner]/[repo]/blob/[...path]/page.tsx', import.meta.url),
  'utf8',
);

test('uses the repository default branch for every blob preview reference', () => {
  assert.match(blobPage, /getRepo,/);
  assert.match(blobPage, /const repoInfo = await getRepo\(owner, repo\);\s+const branch = repoDefaultBranch\(repoInfo\);/);
  assert.doesNotMatch(blobPage, /const branch = 'main'/);

  for (const expression of [
    /getContents\(owner, repo, path, branch\)/,
    /getRawFile\(owner, repo, path, branch\)/,
    /forgejoRawUrl\(owner, repo, path, branch\)/,
    /forgejoTreeUrl\(owner, repo, path, branch\)/,
    /forgejoCommitsUrl\(owner, repo, path, branch\)/,
    /nyankofaceDownloadUrl\(owner, repo, path, branch, lfs \? 'lfs' : 'raw'\)/,
  ]) {
    assert.match(blobPage, expression);
  }
});
