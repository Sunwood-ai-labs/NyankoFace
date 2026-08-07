import { NextRequest, NextResponse } from 'next/server';
import {
  canControlSpace,
  canStartPublicSpace,
  controlToken,
  RUNNER_API,
} from '@/lib/space-control';

export const dynamic = 'force-dynamic';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string; action: string }> },
) {
  const totalStartedAt = performance.now();
  const resolvedParams = await params;
  if (resolvedParams.action !== 'start' && resolvedParams.action !== 'stop') {
    return NextResponse.json({ error: 'Unsupported Space action.' }, { status: 404 });
  }

  const authorizationStartedAt = performance.now();
  const denied = resolvedParams.action === 'start'
    ? await canStartPublicSpace(resolvedParams.owner, resolvedParams.repo)
    : await canControlSpace(request, resolvedParams.owner, resolvedParams.repo);
  const authorizationDuration = performance.now() - authorizationStartedAt;
  if (denied) {
    denied.headers.set(
      'Server-Timing',
      `authorization;dur=${authorizationDuration.toFixed(1)}, total;dur=${(performance.now() - totalStartedAt).toFixed(1)}`,
    );
    return denied;
  }

  const token = controlToken();
  if (!token) return NextResponse.json({ error: 'Space control is not configured.' }, { status: 503 });

  const runnerStartedAt = performance.now();
  const response = await fetch(
    `${RUNNER_API}/spaces/${encodeURIComponent(resolvedParams.owner)}/${encodeURIComponent(resolvedParams.repo)}/${resolvedParams.action}`,
    {
      method: 'POST',
      headers: { 'X-NyankoFace-Control-Token': token },
      cache: 'no-store',
    },
  );
  const runnerDuration = performance.now() - runnerStartedAt;
  const text = await response.text();
  return new NextResponse(text, {
    status: response.status,
    headers: {
      'content-type': response.headers.get('content-type') || 'application/json',
      'Server-Timing': [
        `authorization;dur=${authorizationDuration.toFixed(1)}`,
        `runner;dur=${runnerDuration.toFixed(1)}`,
        `total;dur=${(performance.now() - totalStartedAt).toFixed(1)}`,
      ].join(', '),
    },
  });
}
