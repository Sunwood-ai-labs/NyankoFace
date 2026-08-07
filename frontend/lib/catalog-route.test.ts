import assert from 'node:assert/strict';
import test from 'node:test';
import { NextRequest } from 'next/server';
import { GET } from '../app/api/catalog/repositories/route';

test('catalog API returns 400 for unsupported sort and order values', async () => {
  for (const query of ['sort=stars', 'order=sideways', 'topic=private', 'page=0', 'limit=101']) {
    const response = await GET(new NextRequest(`http://nyankoface.local/api/catalog/repositories?${query}`));
    assert.equal(response.status, 400, query);
    const body = await response.json() as { error?: string };
    assert.match(body.error || '', /Unsupported|must be|between/);
  }
});
