import { NextRequest, NextResponse } from 'next/server';
import { canControlSpace, runnerHeaders, RUNNER_API } from '@/lib/space-control';

export const dynamic = 'force-dynamic';

async function mutate(
  method: 'PATCH' | 'DELETE',
  request: NextRequest,
  owner: string,
  repo: string,
  name: string,
) {
  const denied = await canControlSpace(request, owner, repo);
  if (denied) return denied;
  const headers = runnerHeaders();
  if (!headers) {
    return NextResponse.json({ error: 'Space control is not configured.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/environment/${encodeURIComponent(name)}`,
    {
      method,
      headers: method === 'PATCH'
        ? { ...headers, 'Content-Type': 'application/json' }
        : headers,
      body: method === 'PATCH' ? await request.text() : undefined,
      cache: 'no-store',
    },
  );
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { 'content-type': 'application/json', 'Cache-Control': 'private, no-store' },
  });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string; name: string }> },
) {
  const { owner, repo, name } = await params;
  return mutate('PATCH', request, owner, repo, name);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string; name: string }> },
) {
  const { owner, repo, name } = await params;
  return mutate('DELETE', request, owner, repo, name);
}

