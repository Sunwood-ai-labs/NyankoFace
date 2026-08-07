import { NextRequest, NextResponse } from 'next/server';
import { canControlSpace, runnerHeaders, RUNNER_API } from '@/lib/space-control';

export const dynamic = 'force-dynamic';

async function authorize(
  request: NextRequest,
  owner: string,
  repo: string,
): Promise<{ denied: Response | null; headers: HeadersInit | null }> {
  const denied = await canControlSpace(request, owner, repo);
  if (denied) return { denied, headers: null };
  const headers = runnerHeaders();
  if (!headers) {
    return {
      denied: NextResponse.json({ error: 'Space control is not configured.' }, { status: 503 }),
      headers: null,
    };
  }
  return { denied: null, headers };
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const { denied, headers } = await authorize(request, owner, repo);
  if (denied) return denied;
  if (!headers) {
    return NextResponse.json({ error: 'Space control is not configured.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/environment`,
    { headers, cache: 'no-store' },
  );
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { 'content-type': 'application/json', 'Cache-Control': 'private, no-store' },
  });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const { denied, headers } = await authorize(request, owner, repo);
  if (denied) return denied;
  if (!headers) {
    return NextResponse.json({ error: 'Space control is not configured.' }, { status: 503 });
  }
  const body = await request.text();
  const response = await fetch(
    `${RUNNER_API}/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/environment`,
    {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body,
      cache: 'no-store',
    },
  );
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { 'content-type': 'application/json', 'Cache-Control': 'private, no-store' },
  });
}
