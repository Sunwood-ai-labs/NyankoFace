import { NextRequest, NextResponse } from 'next/server';
import {
  canControlRepository,
  runnerHeaders,
  RUNNER_API,
} from '@/lib/space-control';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const denied = await canControlRepository(request, owner, repo);
  if (denied) return denied;
  const headers = runnerHeaders();
  if (!headers) {
    return NextResponse.json({ error: 'Pipeline control is unavailable.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/pipelines/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
    { headers, cache: 'no-store' },
  );
  return NextResponse.json(await response.json(), { status: response.status });
}
