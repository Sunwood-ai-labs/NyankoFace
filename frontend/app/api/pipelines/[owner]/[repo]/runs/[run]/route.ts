import { NextRequest, NextResponse } from 'next/server';
import {
  canControlRepository,
  runnerHeaders,
  RUNNER_API,
} from '@/lib/space-control';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string; run: string }> },
) {
  const { owner, repo, run } = await params;
  const denied = await canControlRepository(request, owner, repo);
  if (denied) return denied;
  if (!/^\d+$/.test(run)) {
    return NextResponse.json({ error: 'Invalid pipeline run.' }, { status: 422 });
  }
  const headers = runnerHeaders();
  if (!headers) {
    return NextResponse.json({ error: 'Pipeline control is unavailable.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/pipelines/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/runs/${run}`,
    { headers, cache: 'no-store' },
  );
  return NextResponse.json(await response.json(), { status: response.status });
}
