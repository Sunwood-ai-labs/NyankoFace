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

test('keeps lazy blockquote continuations inside GitHub alerts', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> first line',
    'continued without a quote marker',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="github-alert" data-alert-type="NOTE"/);
  assert.match(bodyHtml, /first line/);
  assert.match(bodyHtml, /continued without a quote marker/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps non-one ordered lazy continuations inside GitHub alerts', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> paragraph',
    '2. continuation',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="github-alert" data-alert-type="NOTE"/);
  assert.match(bodyHtml, /2\. continuation/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps empty list markers inside an active GitHub alert paragraph', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> paragraph',
    '*',
    '<my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  const alertEnd = bodyHtml.indexOf('</aside>');
  assert.ok(alertEnd >= 0);
  assert.match(bodyHtml.slice(0, alertEnd), /paragraph/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends a GitHub alert before an unquoted fenced code block', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> paragraph',
    '```ts',
    'const outside = true;',
    '```',
    '',
    '# After',
  ].join('\n'));

  const alertEnd = bodyHtml.indexOf('</aside>');
  assert.ok(alertEnd >= 0);
  assert.doesNotMatch(bodyHtml.slice(0, alertEnd), /outside/);
  assert.match(bodyHtml, /<pre[\s\S]*outside/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends a GitHub alert after a quoted fenced code block', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> ```',
    '> code',
    '> ```',
    'outside',
    '',
    '# After',
  ].join('\n'));

  const alertEnd = bodyHtml.indexOf('</aside>');
  assert.ok(alertEnd >= 0);
  assert.doesNotMatch(bodyHtml.slice(0, alertEnd), /outside/);
  assert.match(bodyHtml, /outside/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends a GitHub alert after a quoted GFM table', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> header | value',
    '> --- | ---',
    'outside',
    '',
    '# After',
  ].join('\n'));

  const alertEnd = bodyHtml.indexOf('</aside>');
  assert.ok(alertEnd >= 0);
  assert.doesNotMatch(bodyHtml.slice(0, alertEnd), /outside/);
  assert.match(bodyHtml, /outside/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends a GitHub alert before an interrupting raw HTML block', () => {
  const { bodyHtml } = parseReadme([
    '> [!NOTE]',
    '> paragraph',
    '<div>outside</div>',
    '',
    '# After',
  ].join('\n'));

  const alertEnd = bodyHtml.indexOf('</aside>');
  assert.ok(alertEnd >= 0);
  assert.doesNotMatch(bodyHtml.slice(0, alertEnd), /outside/);
  assert.match(bodyHtml, /<div>outside<\/div>/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('requires at most one padding space before a GitHub alert marker', () => {
  const { bodyHtml } = parseReadme('>  [!NOTE]\n> This remains an ordinary blockquote.');

  assert.doesNotMatch(bodyHtml, /data-markdown-block="github-alert"/);
  assert.match(bodyHtml, /<blockquote>/);
  assert.match(bodyHtml, /\[!NOTE\]/);

  const tabIndented = parseReadme('\t> [!NOTE]\n\t> This remains indented code.');
  assert.doesNotMatch(tabIndented.bodyHtml, /data-markdown-block="github-alert"/);
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

test('keeps compact and spaced self-closing HTML blocks open until a blank line', () => {
  for (const tag of ['<hr />', '<hr/>']) {
    const { bodyHtml } = parseReadme([
      ':::message',
      tag,
      ':::',
      '',
      ':::',
      '',
      '# After',
    ].join('\n'));

    assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1, tag);
    assert.match(bodyHtml, /<hr\s*\/>/, tag);
    assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/, tag);
  }
});

test('does not treat spaces after a self-closing slash as raw HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<my-widget / >',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat trailing text after a custom self-closing tag as an HTML block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<my-widget/> inline text',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /inline text/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps quoted angle brackets inside custom HTML attributes', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<my-widget title="a>b">',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps trailing content after a closing block tag inside raw HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '</div> trailing',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<\/div> trailing/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not close explicit-end HTML on spaced pseudo-closers', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<pre>',
    '</pre >',
    ':::',
    '',
    '</pre>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<pre>/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat lowercase CDATA openers as raw HTML blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<![cdata[',
    ':::',
    ']]>',
    ':::message',
    'After',
    ':::',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 2);
  assert.match(bodyHtml, /]]&gt;/);
});

test('does not treat malformed custom HTML attributes as a raw block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<my-widget = >',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /&lt;my-widget = &gt;/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not let a type-7 HTML tag interrupt a paragraph', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '<my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /paragraph/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('preserves paragraph continuation before a type-7 HTML tag', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '    continuation',
    '<my-widget>',
    ':::',
    '</my-widget>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /paragraph/);
  assert.match(bodyHtml, /continuation/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps deeply indented HTML-like lines inside an active paragraph', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '    <!-- closed -->',
    '<my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /paragraph/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps non-one ordered markers inside an active paragraph', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '2. continuation',
    '<my-widget>',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /continuation/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not parse a non-one ordered directive inside an active paragraph', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '2. :::details Inner',
    '   :::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not parse tab-indented Zenn directives', () => {
  const { bodyHtml } = parseReadme([
    '\t:::message',
    '\tbody',
    '\t:::',
    '',
    '# After',
  ].join('\n'));

  assert.doesNotMatch(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps a type-7 closing tag inside an active paragraph', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '</span>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /paragraph/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('resets paragraph state after a heading before type-7 HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '# Heading',
    '<my-widget>',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /Heading/);
  assert.match(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('resets paragraph state after asterisk and underscore thematic breaks', () => {
  for (const thematicBreak of ['***', '___']) {
    const { bodyHtml } = parseReadme([
      ':::message',
      thematicBreak,
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
  }
});

test('resets paragraph state after list and blockquote blocks before type-7 HTML', () => {
  for (const containerLine of ['- item', '> quote']) {
    const { bodyHtml } = parseReadme([
      ':::message',
      containerLine,
      '<my-widget>',
      ':::',
      '</my-widget>',
      '',
      ':::',
      '',
      '# After',
    ].join('\n'));

    assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
    assert.match(bodyHtml, /:::/);
    assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
  }
});

test('resets paragraph state after short hyphen setext underlines', () => {
  for (const underline of ['-', '--']) {
    const { bodyHtml } = parseReadme([
      ':::message',
      'Heading',
      underline,
      '<my-widget>',
      ':::',
      '',
      ':::',
      '',
      '# After',
    ].join('\n'));

    assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1, underline);
    assert.match(bodyHtml, /:::/, underline);
    assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/, underline);
  }
});

test('does not treat an orphan short setext line as a block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '--',
    '<my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat an orphan equals setext line as a block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '===',
    '<my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('resets paragraph state after GFM table delimiters', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '| header |',
    '| --- |',
    '<my-widget>',
    ':::',
    '</my-widget>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<table>/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not reset paragraph state for orphan or mismatched GFM delimiters', () => {
  for (const lines of [
    ['plain paragraph', '| --- | --- |'],
    ['| header |', '| --- | --- |'],
    ['| header |', '| - |'],
  ]) {
    const { bodyHtml } = parseReadme([
      ':::message',
      ...lines,
      '<my-widget>',
      ':::',
      '',
      ':::',
      '',
      '# After',
    ].join('\n'));

    assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
    assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
  }
});

test('counts GFM table cells outside escaped and code-span pipes', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '| header \\| value | `a\\|b` |',
    '| --- | --- |',
    '<my-widget>',
    ':::',
    '</my-widget>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /<table>/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not borrow a later closer for an unmatched Zenn opener', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'unclosed',
    '',
    ':::message',
    'valid',
    ':::',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<p>:::message\s*unclosed<\/p>/);
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

test('keeps multiline explicit-end HTML open until its closing tag', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<pre',
    'class="language-text">',
    ':::',
    '</pre>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps multiline type-6 HTML open until a blank line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    'paragraph',
    '<div',
    'class="x">',
    ':::',
    '',
    'inside',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /data-markdown-block="zenn-message"[\s\S]*inside[\s\S]*<h1[^>]*>After<\/h1>/);
});

test('keeps same-line explicit-end HTML inside a Zenn block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<pre class="x">text</pre>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /text/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('keeps explicit-end self-closing tags open until their exact closing tag', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<pre />',
    ':::',
    '</pre>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<pre/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('resets paragraph state after a same-line explicit HTML block', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<pre></pre>',
    '<my-widget>',
    ':::',
    '</my-widget>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<pre><\/pre>[\s\S]*:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('recognizes list-nested raw HTML before Zenn closers', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- <div>',
    '  :::',
    '  </div>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('ends list-nested raw HTML when a Zenn closer deindents', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- <div>',
    '  list HTML',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /list HTML/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('recognizes empty list items before type-7 HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '-',
    '<my-widget>',
    ':::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('tracks fences started on a later list-item continuation line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- item',
    '  ```',
    '  code',
    '- after',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat custom closing tags with trailing text as raw HTML blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '</my-widget> trailing',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<p> trailing<\/p>/);
  assert.doesNotMatch(bodyHtml, /my-widget/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('carries list indentation into continued raw HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- item',
    '',
    '  <my-widget>',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('carries list indentation into continued nested directives', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- item',
    '',
    '  :::details Inner',
    '  body',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('recognizes whitespace before custom closing tag brackets', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '</my-widget >',
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

test('keeps omitted type-6 HTML tags inside a Zenn block', () => {
  for (const tagName of ['option', 'optgroup', 'param', 'frame', 'frameset']) {
    const { bodyHtml } = parseReadme([
      ':::message',
      'paragraph',
      '<' + tagName + '>',
      ':::',
      '</' + tagName + '>',
      '',
      'inside',
      ':::',
      '',
      '# After',
    ].join('\n'));

    assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1, tagName);
    assert.match(bodyHtml, /data-markdown-block="zenn-message"[\s\S]*<p>inside<\/p>[\s\S]*<h1[^>]*>After<\/h1>/, tagName);
  }
});

test('closes declaration HTML at its first angle bracket', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '<!DOCTYPE html>   ',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
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

test('does not treat tab-indented fences as Zenn code fences', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '\t```',
    '\tcode',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('expands mixed leading whitespace at tab stops before rendering code', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    ' \tcode',
    ':::',
  ].join('\n'));

  assert.match(bodyHtml, /<code[^>]*>code<\/code>/);
  assert.doesNotMatch(bodyHtml, /<code[^>]*> code<\/code>/);
});

test('resets paragraph state after indented code before type-7 HTML', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '    code',
    '<my-widget>',
    ':::',
    '</my-widget>',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /:::/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
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

test('tracks list fences beyond the preceding marker line', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- item',
    '  paragraph',
    '  ```',
    '  code',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('measures list-nested Zenn fences at tab-stop columns', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '-\t```',
    '    list code',
    '  :::',
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

test('measures list-nested raw HTML at tab-stop columns', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '-\t<my-widget>',
    '  :::',
    '',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('does not treat over-padded list directives as nested Zenn blocks', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '-     :::details Over-padded',
    '  literal continuation',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.doesNotMatch(bodyHtml, /<details/);
  assert.match(bodyHtml, /:::details Over-padded/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('tracks top-level Zenn blocks nested inside containers', () => {
  const { bodyHtml } = parseReadme([
    '- :::message',
    '  Container body',
    '  :::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
  assert.match(bodyHtml, /Container body/);
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

test('tracks Zenn blocks nested after ordered list markers', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '2) :::details Nested',
    '   Ordered nested body',
    '   :::',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.match(bodyHtml, /data-markdown-block="zenn-message"/);
  assert.match(bodyHtml, /<details/);
  assert.match(bodyHtml, /Ordered nested body/);
  assert.match(bodyHtml, /<h1[^>]*>After<\/h1>/);
});

test('matches a top-level closer after an unmatched list-nested directive', () => {
  const { bodyHtml } = parseReadme([
    ':::message',
    '- :::details Inner',
    '  body',
    ':::',
    '',
    '# After',
  ].join('\n'));

  assert.equal((bodyHtml.match(/data-markdown-block="zenn-message"/g) || []).length, 1);
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
