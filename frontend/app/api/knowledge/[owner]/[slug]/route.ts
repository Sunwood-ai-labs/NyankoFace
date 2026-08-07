import { NextRequest, NextResponse } from 'next/server';
import { getKnowledgeArticle } from '@/lib/knowledge';
import { knowledgeResponseHeaders } from '@/lib/knowledge-api';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ owner: string; slug: string }> },
) {
  const { owner, slug } = await params;
  const article = await getKnowledgeArticle(owner, slug);
  if (!article) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  const modified = new Date(article.updatedAt);
  const headers = knowledgeResponseHeaders(article);
  if (!Number.isNaN(modified.getTime())) headers['Last-Modified'] = modified.toUTCString();
  return NextResponse.json(article, {
    headers,
  });
}
