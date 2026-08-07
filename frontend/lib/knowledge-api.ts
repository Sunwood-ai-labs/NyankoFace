import { createHash } from 'node:crypto';

export function knowledgeResponseHeaders(article: unknown): Record<string, string> {
  const representation = JSON.stringify(article);
  const etag = `"sha256-${createHash('sha256').update(representation).digest('hex')}"`;
  return {
    ETag: etag,
    // Published content may become private between requests. Shared caches may
    // store this representation, but must revalidate visibility before reuse.
    'Cache-Control': 'public, no-cache, must-revalidate',
  };
}
