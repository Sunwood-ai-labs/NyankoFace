import { NextRequest, NextResponse } from 'next/server';
import {
  canControlRepository,
  controlActor,
  postNativeForgejoAction,
  runnerHeaders,
  RUNNER_API,
} from '@/lib/space-control';

export async function POST(
  request: NextRequest,
  { params }: {
    params: Promise<{ owner: string; repo: string; run: string; job: string }>;
  },
) {
  const { owner, repo, run, job } = await params;
  const denied = await canControlRepository(request, owner, repo);
  if (denied) return denied;
  if (!/^\d+$/.test(run) || !/^\d+$/.test(job)) {
    return NextResponse.json({ error: 'Invalid pipeline job.' }, { status: 422 });
  }
  const headers = runnerHeaders(await controlActor(request));
  if (!headers) {
    return NextResponse.json({ error: 'Pipeline control is unavailable.' }, { status: 503 });
  }
  const response = await fetch(
    `${RUNNER_API}/pipelines/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/runs/${run}/jobs/${job}/rerun`,
    { method: 'POST', headers, cache: 'no-store' },
  );
  const payload = await response.json();
  if (!response.ok) {
    return NextResponse.json(payload, { status: response.status });
  }
  if (
    payload?.status === 'native_action_required'
    && typeof payload.native_action_url === 'string'
  ) {
    const nativeResponse = await postNativeForgejoAction(
      request,
      payload.native_action_url,
    );
    const nativePayload = await nativeResponse.json().catch(() => ({}));
    if (!nativeResponse.ok) {
      return NextResponse.json(
        {
          error: nativeResponse.status === 404
            ? 'Forgejo sign-in with repository write permission is required.'
            : 'Forgejo could not rerun this job.',
          native: nativePayload,
        },
        { status: nativeResponse.status === 404 ? 401 : nativeResponse.status },
      );
    }
    return NextResponse.json({
      ...payload,
      status: 'accepted',
      native: nativePayload,
    });
  }
  return NextResponse.json(payload, { status: response.status });
}
