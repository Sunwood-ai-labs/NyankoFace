import { NextRequest, NextResponse } from 'next/server';
import {
  canControlRepository,
  controlActor,
  runnerHeaders,
  RUNNER_API,
} from '@/lib/space-control';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const denied = await canControlRepository(request, owner, repo);
  if (denied) return denied;
  const headers = runnerHeaders(await controlActor(request));
  if (!headers) {
    return NextResponse.json({ error: 'Pipeline control is unavailable.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/pipelines/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/dispatch`,
    {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(await request.json()),
      cache: 'no-store',
    },
  );
  return NextResponse.json(await response.json(), { status: response.status });
}
