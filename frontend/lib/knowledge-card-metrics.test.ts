import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { KnowledgeLikeCount } from '../components/DocsDirectoryPage';

test('knowledge likes render an unavailable marker instead of a fabricated zero', () => {
  const html = renderToStaticMarkup(createElement(KnowledgeLikeCount, {
    available: false,
    likes: 0,
    locale: 'ja',
  }));

  assert.match(html, /data-metric-state="unavailable"/);
  assert.match(html, /title="いいね数を取得できません"/);
  assert.match(html, />—<\/span>/);
  assert.doesNotMatch(html, />0<\/span>/);
});

test('knowledge likes render the recorded value when metrics are available', () => {
  const html = renderToStaticMarkup(createElement(KnowledgeLikeCount, {
    available: true,
    likes: 12,
    locale: 'en',
  }));

  assert.match(html, /data-metric-state="available"/);
  assert.match(html, /title="12 repository likes"/);
  assert.match(html, />12<\/span>/);
});
