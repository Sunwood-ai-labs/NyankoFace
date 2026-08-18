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

test('renders every GitHub alert as a typed callout instead of a generic blockquote', () => {
  const source = [
    ['NOTE', '補足情報です。'],
    ['TIP', 'ヒントです。'],
    ['IMPORTANT', '重要な情報です。'],
    ['WARNING', '注意が必要です。'],
    ['CAUTION', '危険性のある操作です。'],
  ].flatMap(([type, text]) => [`> [!${type}]`, `> ${text}`, '']).join('\n');
  const { bodyHtml } = parseReadme(source, { locale: 'ja' });

  for (const type of ['NOTE', 'TIP', 'IMPORTANT', 'WARNING', 'CAUTION']) {
    assert.match(bodyHtml, new RegExp(`data-markdown-block="github-alert" data-alert-type="${type}"`));
  }
  assert.match(bodyHtml, /<span>補足<\/span>/);
  assert.match(bodyHtml, /<span>ヒント<\/span>/);
  assert.match(bodyHtml, /<span>重要<\/span>/);
  assert.match(bodyHtml, /<span>警告<\/span>/);
  assert.match(bodyHtml, /<span>注意<\/span>/);
  assert.doesNotMatch(bodyHtml, /<blockquote>/);
});

test('requires at most one padding space before a GitHub alert marker', () => {
  const { bodyHtml } = parseReadme('>  [!NOTE]\n> This remains an ordinary blockquote.');

  assert.doesNotMatch(bodyHtml, /data-markdown-block="github-alert"/);
  assert.match(bodyHtml, /<blockquote>/);
  assert.match(bodyHtml, /\[!NOTE\]/);
});

test('renders Zenn message and details blocks through the shared safe Markdown pipeline', () => {
  const source = [
    ':::message',
    '# Message heading',
    '',
    '[Guide](./guide.md)',
    '',
    '```ts',
    'const safe = true;',
    '```',
    ':::',
    '',
    ':::message  alert',
    '警告メッセージ',
    ':::',
    '',
    ':::details 詳細を表示',
    '- [x] Complete',
    '- [ ] Pending',
    '',
    ':::message',
    'Nested message',
    ':::',
    ':::',
    '',
    ':::unsupported',
    '<script>alert(1)</script>',
    ':::',
    '',
    '# After',
  ].join('\n');
  const { bodyHtml } = parseReadme(source, {
    relativeLinkBaseUrl: '/owner/repo/blob/main/',
    locale: 'ja',
  });

  assert.match(bodyHtml, /data-markdown-block="zenn-message" data-message-variant="default"/);
  assert.match(bodyHtml, /data-markdown-block="zenn-message" data-message-variant="alert"/);
  assert.match(bodyHtml, /<details[^>]*><summary[^>]*>詳細を表示<\/summary>/);
  assert.match(bodyHtml, /<h1[^>]*>Message heading<\/h1>/);
  assert.match(bodyHtml, /href="\/owner\/repo\/blob\/main\/guide\.md"/);
  assert.match(bodyHtml, /class="nyankoface-code-block"/);
  assert.match(bodyHtml, /<input checked disabled type="checkbox" \/>/);
  assert.match(bodyHtml, /<input disabled type="checkbox" \/>/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 3);
  assert.match(bodyHtml, /:::unsupported/);
  assert.doesNotMatch(bodyHtml, /<script|javascript:/i);
});

test('keeps Zenn block boundaries aligned when README input uses CRLF', () => {
  const { bodyHtml } = parseReadme(':::message\r\nCRLF body\r\n:::\r\n\r\n# After\r\n');

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /CRLF body/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not parse Zenn delimiters inside raw HTML blocks', () => {
  const { bodyHtml } = parseReadme([
    '<div class="raw-content">',
    ':::message',
    'This is literal HTML content.',
    ':::',
    '</div>',
    '',
    ':::message',
    'This is a Markdown message.',
    ':::',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::message/);
  assert.match(bodyHtml, /This is a Markdown message\./);
});

test('does not parse Zenn delimiters inside textarea raw HTML blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<textarea>',
    ':::',
    '</textarea>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.doesNotMatch(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not parse Zenn delimiters inside CDATA raw HTML blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<![CDATA[',
    ':::',
    ']]>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.doesNotMatch(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps type-6 HTML blocks open until a blank line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<div>raw</div>',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<div>raw<\/div>\n:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps type-7 custom HTML blocks open until a blank line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<my-widget>',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat incomplete inline HTML as a raw block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<span>inline text',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends block HTML boundaries at a blank line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<div>',
    'Literal HTML content.',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not close a Zenn block on a fenced code line with language info', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '```',
    '```ts',
    ':::',
    '```',
    ':::',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /```ts/);
  assert.doesNotMatch(bodyHtml, /data-markdown-block="zenn-details"/);
});

test('keeps container-prefixed fence-like lines inside a plain fenced block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '```',
    '> ```',
    ':::',
    '```',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /&gt; ```/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('tracks fenced code nested under a list marker inside a Zenn block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- ```text',
    '  :::',
    '  ```',
    '- after',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('tracks Zenn blocks nested immediately after a list marker', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- :::details Nested',
    '  Nested body',
    '  :::',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('tracks nested Zenn closers after four-space list indentation', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '-   :::details Nested',
    '    Nested body',
    '    :::',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<details/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat four-space indented directives as nested Zenn blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '    :::message',
    '    literal code',
    '    :::',
    ':::',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::message/);
});

test('reuses one boundary index for deeply nested Zenn blocks', () => {
  const depth = 60;
  const source = [
    ...Array.from({ length: depth }, (_, index) => index % 2 === 0 ? ':::message' : ':::details Nested'),
    'Nested body',
    ...Array.from({ length: depth }, () => ':::'),
    '',
    '# After',
  ].join('\n');

  const { bodyHtml } = parseReadme(source);
  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<details/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('closes a Zenn block when a blockquote fence container ends', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '> ```js',
    '> const value = true;',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat backticks in a fence info string as a valid opener', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '```foo```',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not rescan every unmatched Zenn opener', () => {
  const source = Array.from({ length: 300 }, () => ':::message').join('\n');
  const { bodyHtml } = parseReadme(source);

  assert.match(bodyHtml, /:::message/);
});
