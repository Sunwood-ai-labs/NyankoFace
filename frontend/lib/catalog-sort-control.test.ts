import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import CatalogSortControl, { CatalogOrderingInputs } from '../components/CatalogSortControl';

test('search ordering inputs preserve the active sort and direction', () => {
  const html = renderToStaticMarkup(createElement(CatalogOrderingInputs, {
    sort: 'views',
    order: 'asc',
  }));
  assert.match(html, /type="hidden" name="sort" value="views"/);
  assert.match(html, /type="hidden" name="order" value="asc"/);
});

test('sort control preserves filters and exposes the selected metric direction', () => {
  const html = renderToStaticMarkup(createElement(CatalogSortControl, {
    action: '/models',
    locale: 'ja',
    sort: 'likes',
    order: 'asc',
    preserve: { q: 'audio', tag: 'speech' },
  }));
  assert.match(html, /action="\/models"/);
  assert.match(html, /name="q" value="audio"/);
  assert.match(html, /name="tag" value="speech"/);
  assert.match(html, /<option value="likes" selected="">いいね<\/option>/);
  assert.match(html, /<option value="asc" selected="">少ない／古い順<\/option>/);
});
