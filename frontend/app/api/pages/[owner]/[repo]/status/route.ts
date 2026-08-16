import { NextResponse } from 'next/server';
import { pagesRunnerUrl } from '@/lib/pages-control';
import { sanitizePublicUrlJson } from '@/lib/public-origin';

export const dynamic = 'force-dynamic';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const response = await fetch(pagesRunnerUrl(owner, repo, 'status'), {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  });
  return new NextResponse(sanitizePublicUrlJson(await response.text()), {
    status: response.status,
    headers: {
      'content-type': response.headers.get('content-type') || 'application/json',
      'cache-control': 'no-store',
    },
  });
}
