import assert from 'node:assert/strict';
import test from 'node:test';
import { parseReadme } from './markdown';

const languageSamples: Record<string, string> = {
  javascript: 'const answer = 42; // meaning',
  typescript: 'type User = { active: boolean };',
  jsx: 'export const App = () => <main>Hello</main>;',
  tsx: 'export const App = ({ name }: { name: string }) => <p>{name}</p>;',
  python: 'def greet(name: str):\n    return f"Hello {name}"',
  bash: 'printf "%s\\n" "$HOME"',
  powershell: 'Get-ChildItem | Where-Object { $_.Length -gt 10 }',
  html: '<main class="hero">Hello</main>',
  css: '.hero { color: rebeccapurple; }',
  json: '{"enabled": true, "count": 3}',
  yaml: 'service:\n  enabled: true',
  toml: '[service]\nenabled = true',
  markdown: '# Heading\n\n**Strong**',
  sql: 'SELECT id FROM users WHERE active = true;',
  dockerfile: 'FROM node:22-alpine\nRUN npm ci',
  diff: '-before\n+after',
  text: 'no tokens required',
};

test('renders the supported language registry through one shared code surface', () => {
  for (const [language, source] of Object.entries(languageSamples)) {
    const { bodyHtml } = parseReadme(`\`\`\`${language}\n${source}\n\`\`\``);
    assert.match(bodyHtml, /class="nyankoface-code-block"/, language);
    assert.match(bodyHtml, new RegExp(`data-language="${language}"`), language);
    assert.match(bodyHtml, /data-nyankoface-copy-code(?:="")?/, language);
    assert.match(bodyHtml, /tabindex="0"/, language);
    if (language !== 'text') assert.match(bodyHtml, /class="hljs-/, `${language} should emit syntax tokens`);
    assert.doesNotMatch(bodyHtml, /<script/i, language);
  }
});

test('renders a filename and language in the accessible code header', () => {
  const { bodyHtml } = parseReadme('```ts title="src/example.ts"\nconst safe = true;\n```');
  assert.match(bodyHtml, /class="nyankoface-code-label" title="src\/example\.ts">src\/example\.ts<\/span>/);
  assert.match(bodyHtml, /class="nyankoface-code-language">ts<\/span>/);
  assert.match(bodyHtml, /aria-label="Copy ts code"/);
});

test('localizes the initial copy control without a hydration-time language swap', () => {
  const { bodyHtml } = parseReadme('```json\n{"safe": true}\n```', { locale: 'ja' });
  assert.match(bodyHtml, /aria-label="jsonのコードをコピー">コピー<\/button>/);
});

test('falls back to escaped plain text for unknown languages', () => {
  const { bodyHtml } = parseReadme('```made-up-language\n<tag onclick="bad()">& text\n```');
  assert.match(bodyHtml, /data-language="text" data-language-known="false"/);
  assert.match(bodyHtml, /&lt;tag onclick=(?:&quot;|")bad\(\)(?:&quot;|")&gt;&amp; text/);
  assert.doesNotMatch(bodyHtml, /<tag/);
});

test('sanitizes raw HTML while preserving safe repository content and relative URLs', () => {
  const { bodyHtml } = parseReadme(
    '<script>alert(1)</script>\n\n<img src="images/example.png" onerror="alert(2)">\n\n<a href="javascript:alert(3)">bad</a>',
    { assetBaseUrl: '/api/raw/nyankoface/demo/main/', relativeLinkBaseUrl: '/nyankoface/demo/blob/main/' },
  );
  assert.doesNotMatch(bodyHtml, /<script|onerror|javascript:/i);
  assert.match(bodyHtml, /src="\/api\/raw\/nyankoface\/demo\/main\/images\/example\.png"/);
  assert.match(bodyHtml, /rel="nofollow noreferrer"/);
});

test('keeps Mermaid source available for the client renderer and styles inline code separately', () => {
  const { bodyHtml } = parseReadme('Use `npm run build`.\n\n```mermaid\ngraph TD; A-->B\n```');
  assert.match(bodyHtml, /<code>npm run build<\/code>/);
  assert.match(bodyHtml, /<pre><code class="language-mermaid">graph TD; A--&gt;B<\/code><\/pre>/);
  assert.doesNotMatch(bodyHtml, /nyankoface-code-block[^]*language-mermaid/);
});

test('preserves safe details, task lists, and repository-relative assets', () => {
  const { bodyHtml } = parseReadme(
    '<details><summary>More</summary>Safe content</details>\n\n- [x] Complete\n- [ ] Pending\n\n![Diagram](assets/diagram.png)',
    { assetBaseUrl: '/api/raw/nyankoface/demo/main/' },
  );
  assert.match(bodyHtml, /<details><summary>More<\/summary>Safe content<\/details>/);
  assert.match(bodyHtml, /<input checked disabled type="checkbox" \/>/);
  assert.match(bodyHtml, /<input disabled type="checkbox" \/>/);
  assert.match(bodyHtml, /src="\/api\/raw\/nyankoface\/demo\/main\/assets\/diagram\.png"/);
});

test('resolves nested README links and images within the same repository ref', () => {
  const { bodyHtml } = parseReadme(
    '# Nested README\n\n[Guide](../guide.md?view=full#install)\n\n![Diagram](./assets/diagram.png)\n\n[Section](#nested-readme)\n\n[External](https://example.com/docs)\n\n[Absolute](/docs/overview)',
    {
      assetBaseUrl: '/git/nyankoface/demo/raw/branch/main/docs/',
      relativeLinkBaseUrl: '/git/nyankoface/demo/src/branch/main/docs/',
    },
  );
  assert.match(bodyHtml, /href="\/git\/nyankoface\/demo\/src\/branch\/main\/guide\.md\?view=full#install"/);
  assert.match(bodyHtml, /src="\/git\/nyankoface\/demo\/raw\/branch\/main\/docs\/assets\/diagram\.png"/);
  assert.match(bodyHtml, /href="#nested-readme"/);
  assert.match(bodyHtml, /href="https:\/\/example\.com\/docs"/);
  assert.match(bodyHtml, /href="\/docs\/overview"/);
});

test('keeps empty README bodies empty for an explanatory page fallback', () => {
  assert.equal(parseReadme(null).bodyHtml, '');
  assert.equal(parseReadme('').bodyHtml, '');
  assert.equal(parseReadme('---\ntitle: metadata only\n---').bodyHtml, '');
});
