import { NextRequest, NextResponse } from 'next/server';
import { controlToken } from '@/lib/space-control';
import { canDeployPages, pagesRunnerUrl } from '@/lib/pages-control';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const authorization = await canDeployPages(request, owner, repo);
  if (authorization.denied) return authorization.denied;

  const token = controlToken();
  if (!token) {
    return NextResponse.json(
      { error: 'Pages deployment is not configured.' },
      { status: 503 },
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: 'A JSON deployment request is required.' },
      { status: 400 },
    );
  }
  const response = await fetch(pagesRunnerUrl(owner, repo, 'deploy'), {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'X-NyankoFace-Control-Token': token,
      'X-NyankoFace-Actor': authorization.actor,
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: {
      'content-type': response.headers.get('content-type') || 'application/json',
    },
  });
}
