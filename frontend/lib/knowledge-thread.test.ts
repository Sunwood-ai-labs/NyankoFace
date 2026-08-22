import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parseReadme, renderMarkdownBody } from './markdown';
import { isThreadKnowledge, parseKnowledgeThread, safeKnowledgeHref } from './knowledge-thread';

const newKnowledgeSource = readFileSync(new URL('../app/new/page.tsx', import.meta.url), 'utf8');
const detailSource = readFileSync(new URL('../app/docs/[owner]/[slug]/page.tsx', import.meta.url), 'utf8');
const directorySource = readFileSync(new URL('../components/DocsDirectoryPage.tsx', import.meta.url), 'utf8');
const threadViewSource = readFileSync(new URL('../components/KnowledgeThreadView.tsx', import.meta.url), 'utf8');

test('parses thread metadata, ordered posts, and half/full-width reply anchors', () => {
  const frontmatter = {
    format: 'thread',
    thread: {
      part: 'Part.2',
      theme: 'なぜこの仕組みは動くのか',
      rules: ['短く具体的に書く'],
      sources: [
        { label: '仕様書', url: 'https://example.com/spec' },
        { label: '拒否するURL', url: 'javascript:alert(1)' },
      ],
    },
    posts: [
      { number: 1, name: '名無しさん', body: 'まず全体像を教えてください。' },
      { number: 2, name: '解説役', role: '回答', id: 'abc123', body: '>>1\n＞＞1 に答えます。', posted_at: '2026-08-22T10:00:00+09:00' },
    ],
  };

  assert.equal(isThreadKnowledge(frontmatter), true);
  const thread = parseKnowledgeThread(frontmatter);
  assert.ok(thread);
  assert.deepEqual(thread.metadata, {
    part: 'Part.2',
    theme: 'なぜこの仕組みは動くのか',
    rules: ['短く具体的に書く'],
    sources: [{ label: '仕様書', url: 'https://example.com/spec' }],
  });
  assert.deepEqual(thread.posts.map((post) => ({
    number: post.number,
    name: post.name,
    role: post.role,
    id: post.id,
    postedAt: post.postedAt,
    replyTo: post.replyTo,
  })), [
    { number: 1, name: '名無しさん', role: undefined, id: undefined, postedAt: undefined, replyTo: [] },
    { number: 2, name: '解説役', role: '回答', id: 'abc123', postedAt: '2026-08-22T10:00:00+09:00', replyTo: [1] },
  ]);
});

test('keeps ordinary knowledge articles on the regular format path', () => {
  assert.equal(isThreadKnowledge({ format: 'article', posts: [] }), false);
  assert.equal(parseKnowledgeThread({ format: 'article', posts: [] }), null);
});

test('normalizes YAML Date values used for post timestamps', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, posted_at: new Date('2026-08-22T01:00:00.000Z'), body: '本文' }],
  });
  assert.equal(thread?.posts[0]?.postedAt, '2026-08-22T01:00:00.000Z');
});

test('falls back safely for unsafe or oversized post numbers', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [
      { number: '9007199254740992', body: '一つ目' },
      { number: '9007199254740992', body: '二つ目' },
    ],
  });
  assert.deepEqual(thread?.posts.map((post) => post.number), [1, 2]);
});

test('allocates duplicate post numbers without rescanning earlier posts', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: Array.from({ length: 2048 }, (_, index) => ({ number: 1, body: `本文 ${index}` })),
  });
  assert.equal(thread?.posts[0]?.number, 1);
  assert.equal(thread?.posts.at(-1)?.number, 2048);
});

test('does not turn Markdown code operators into reply anchors', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: [
        '計算式は `value >> 1` です。',
        '`value\n>> 2`',
        '```js\nvalue >> 3\n```',
        '    value >> 4',
        '>     value >> 5',
        '> ```js\n> value >> 6\n> ```',
        '- ```js\n  value >> 7\n  ```',
        '<!-- TODO: verify >>8 -->',
        '<!-- multiline >>\n9 -->',
        '<code>value >> 10</code>',
        '<pre>value >> 11</pre>',
        '[guide](https://example.test/thread/>>12)',
        '<a href="https://example.test/thread/>>13">guide</a>',
      ].join('\n\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('does not close a Markdown fence when a marker has info text', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: '```js\n```js\n>>1',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('recognizes escaped and encoded visible reply markers', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '\\>\\>1\n\n&gt;&gt;2' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1, 2]);
});
test('recognizes zero-padded greater-than entities', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '&#062;&#x03E;1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('ignores reference-style link identifiers in reply anchors', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[guide][ticket>>1]\n\n[ticket>>1]: https://example.test' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});
test('preserves visible replies after unmatched Markdown link brackets', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: Array.from({ length: 4096 }, () => '[').join('') + ' visible >>1',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('preserves leading whitespace in thread post Markdown', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '\n    value >> 1\n' }],
  });
  assert.equal(thread?.posts[0]?.bodyMarkdown, '    value >> 1');
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});
test('does not enter invalid backtick fences', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['```lang`x', '\\>\\>1'].join('\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('does not close an inline code span with a longer delimiter run', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: '` text \\>\\>1 ```',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});
test('keeps visible replies after hidden HTML inside fenced code', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: ['```html', '<!-- example', '```', '\\>\\>1'].join('\n') }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('keeps reply markers in indented paragraph continuations', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '説明\n    \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});
test('preserves ASCII reply markers before blockquote stripping', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '>>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});
test('recognizes the maximum accepted reply number', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '>>1000000' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1000000]);
});
test('keeps duplicate maximum post numbers within the accepted range', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1000000, body: '最大' }, { number: 1000000, body: '重複' }],
  });
  assert.deepEqual(thread?.posts.map((post) => post.number), [1000000, 1]);
});

test('preserves undefined reference link identifiers', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[guide][ticket>>1]' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('keeps escaped backticks and their visible reply marker', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: ['\\', '`literal >>1', '\\', '`'].join('') }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('does not treat an indented line after a heading as a paragraph continuation', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '# Heading\n    \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});
test('closes active code spans at escaped source delimiters', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: [String.fromCharCode(96), 'code ', '\\', String.fromCharCode(96), ' visible \\>\\>1 ', String.fromCharCode(96)].join('') }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('keeps replies after inline code containing hidden HTML syntax', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: [String.fromCharCode(96), '<!--', String.fromCharCode(96), ' \\>\\>1'].join('') }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('rejects partially numeric post and reply references', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [
      { number: '2foo', body: '本文' },
      { number: 1, reply_to: '2.5', body: '本文' },
    ],
  });
  assert.deepEqual(thread?.posts.map((post) => post.number), [1, 2]);
  assert.deepEqual(thread?.posts[1]?.replyTo, []);
});
test('preserves replies after incomplete HTML-looking fragments', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<span title="x" ＞＞1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('stops raw-text sanitization at the first matching closing tag', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<script>const sample = "<script>";</script> ＞＞1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('does not infer replies from sanitized non-text HTML', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: [
        "<script>const ref = '>>1';</script>",
        "<style>.thread::before { content: '>>1'; }</style>",
        '<textarea>>>1</textarea>',
      ].join('\n\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});
test('keeps visible replies after comment syntax in HTML attributes', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<span title="<!--">visible</span> >>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('matches later code spans after an unmatched shorter delimiter', () => {
  const tick = String.fromCharCode(96);
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: [tick, 'literal ', tick, tick, 'code >>1', tick, tick, ' ', tick].join('') }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('does not cross code spans across later delimiter runs', () => {
  const tick = String.fromCharCode(96);
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: [tick, 'hidden ', tick, tick, ' text', tick, ' visible >>1 ', tick, tick, ' ', tick].join(''),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('preserves replies in invalid inline link destinations', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[guide](bad destination >>1)' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('does not infer replies from indented lines after Setext headings', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['Heading', '===', '    ' + String.fromCharCode(92) + '>' + String.fromCharCode(92) + '>1'].join(String.fromCharCode(10)),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('preserves replies after incomplete reference definitions', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[guide][ticket>>1]\n\n[ticket>>1]:' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('ignores multiline reference definitions in reply anchors', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: '[guide][ticket>>1]\n\n[ticket>>1]:\n  https://example.test',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('does not infer replies from image alt labels', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '![diagram >>1](image.png)' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('scopes fenced code to its Markdown container', () => {
  const tick = String.fromCharCode(96);
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['> ' + tick + tick + tick, '> example', tick + tick + tick, '>>1'].join(String.fromCharCode(10)),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('ignores reply markers in quoted inline link titles', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[guide](https://example.test "details ) >>1")' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});
test('uses safe source URLs and sends post Markdown through the shared renderer', () => {
  assert.equal(safeKnowledgeHref('https://example.com/source'), 'https://example.com/source');
  assert.equal(safeKnowledgeHref('mailto:author@example.com'), 'mailto:author@example.com');
  assert.equal(safeKnowledgeHref('javascript:alert(1)'), null);

  const html = parseReadme('[bad](javascript:alert(1))\n\n**safe**').bodyHtml;
  assert.doesNotMatch(html, /javascript:/i);
  assert.match(html, /<strong>safe<\/strong>/);
});

test('renders post Markdown without treating thematic breaks as frontmatter', () => {
  const html = renderMarkdownBody('---\n\n本文\n\n---\n\n後半');
  assert.match(html, /本文/);
  assert.match(html, /後半/);
});

test('wires the thread format through creation, directory, and detail surfaces', () => {
  assert.match(newKnowledgeSource, /name="knowledge_format" value="thread"/);
  assert.match(newKnowledgeSource, /format: thread/);
  assert.match(newKnowledgeSource, /title: スレッド解説サンプル/);
  assert.match(newKnowledgeSource, /description: 投稿形式で仕組みを順番に説明します/);
  assert.match(newKnowledgeSource, /data-knowledge-format-help="true"/);
  assert.match(newKnowledgeSource, /<details hidden=\{knowledgeFormat !== 'thread'\}/);
  assert.match(newKnowledgeSource, /data-knowledge-format-fieldset="true"/);
  assert.match(newKnowledgeSource, /syncKnowledgeFormatFieldset/);
  assert.match(newKnowledgeSource, /syncKnowledgeFormatHelp/);
  assert.match(directorySource, /article\.format === 'thread'/);
  assert.match(detailSource, /<KnowledgeThreadView/);
  assert.match(detailSource, /knowledgeRenderUrls/);
  assert.match(threadViewSource, /MarkdownBodyThemeProvider/);
  assert.match(threadViewSource, /renderMarkdownBody\(post\.bodyMarkdown/);
  assert.match(threadViewSource, /renderUrls\?\: ReadmeRenderUrls/);
  assert.match(threadViewSource, /data-thread-post-number/);
  assert.match(threadViewSource, /href=\{`#thread-post-\$\{target\}`\}/);
});


test('preserves visible replies after escaped image markers', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '\\![diagram >>1](image.png)' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});


test('ignores non-element raw HTML tokens in reply inference', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['<?thread >>1?>', '<!DOCTYPE html ">>2">', '<![CDATA[>>3]]>'].join('\n\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('ignores shortcut and collapsed reference image labels', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: [
        '![diagram >>1]',
        '![diagram >>1][]',
        '[diagram >>1]: image.png',
      ].join('\n\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('scopes fenced code to list containers', () => {
  const tick = String.fromCharCode(96);
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['- ' + tick + tick + tick, '  example', ' ' + tick + tick + tick, '>>1'].join('\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});


test('bounds rendered thread posts', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: Array.from({ length: 2049 }, (_, index) => ({ number: index + 1, body: '本文' })),
  });
  assert.equal(thread?.posts.length, 2048);
});

test('does not infer replies from indented code after an HTML block', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<!-- done -->\n    \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});


test('bounds thread rules and sources', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    thread: {
      rules: Array.from({ length: 257 }, (_, index) => 'ルール' + index),
      sources: Array.from({ length: 257 }, (_, index) => ({ label: '資料' + index, url: 'https://example.com/' + index })),
    },
    posts: [],
  });
  assert.equal(thread?.metadata.rules.length, 256);
  assert.equal(thread?.metadata.sources.length, 256);
});

test('ignores multiline reference titles in reply inference', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: '[guide][ticket]\n\n[ticket]: /url\n  "details >>1"',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('keeps visible replies inside type-6 HTML blocks', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<div>\n    \\>\\>1\n</div>' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('uses marker-specific indentation for list fences', () => {
  const tick = String.fromCharCode(96);
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: ['10. ' + tick + tick + tick, '  ＞＞1'].join('\n'),
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});


test('preserves excess list-marker indentation as code', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '-     \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('preserves reply markers in invalid HTML tags', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<span @bad=">>1">' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});


test('recognizes encoded full-width reply markers', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '&#xFF1E;&#65310;1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('does not infer replies from indented code after a table delimiter', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '| h |\n|---|\n    \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});


test('does not infer replies from indented code after a directive block opener', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: ':::message\n    \\>\\>1\n:::' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('preserves replies after unbalanced reference destinations', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '[ticket>>1]: /foo(bar' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('ignores balanced parentheses in reference destinations', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{
      number: 1,
      body: '[guide][ticket]\n\n[ticket]: /foo(bar)',
    }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});


test('does not infer replies after a blockquote container ends', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '> paragraph\n    \\>\\>1' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, []);
});

test('keeps type-6 HTML blocks open through their terminating blank line', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<div>\n</div>\n    ＞＞1\n\n本文' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});

test('preserves replies in invalid HTML declarations', () => {
  const thread = parseKnowledgeThread({
    format: 'thread',
    posts: [{ number: 1, body: '<!123 ＞＞1>' }],
  });
  assert.deepEqual(thread?.posts[0]?.replyTo, [1]);
});
