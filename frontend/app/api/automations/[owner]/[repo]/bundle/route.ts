import { NextRequest, NextResponse } from 'next/server';
import { buildDisabledAutomationBundle } from '@/lib/automation';
import { inspectPublicAutomationRepository } from '@/lib/automation-repository';
import { recordDownloadMetric } from '@/lib/agent-metrics';

export const dynamic = 'force-dynamic';

function safeFileStem(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'automation';
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  let body: { revision?: unknown; acknowledgeWarnings?: unknown; downloadId?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'A JSON request body is required.' }, { status: 400 });
  }
  const revision = typeof body.revision === 'string' ? body.revision.trim() : '';
  const downloadId = typeof body.downloadId === 'string' && /^[A-Za-z0-9._:-]{1,200}$/.test(body.downloadId)
    ? body.downloadId.slice(0, 160)
    : null;
  const actorKind = request.cookies.has('nyankoface_session') ? 'authenticated' : 'anonymous';
  const recordOutcome = (outcome: 'success' | 'failed' | 'cancelled' | 'denied') => {
    if (!downloadId) return;
    void recordDownloadMetric({
      owner,
      repo,
      source: 'automation',
      artifactPath: revision || null,
      idempotencyKey: `automation:${downloadId}:${outcome}`,
      outcome,
      actorKind,
    });
  };
  if (!/^[a-f0-9]{40,64}$/i.test(revision)) {
    recordOutcome('failed');
    return NextResponse.json(
      { error: 'Use the immutable revision returned by preflight.' },
      { status: 400, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  const inspection = await inspectPublicAutomationRepository(owner, repo, revision);
  if (!inspection || inspection.preflight.source?.sha !== revision) {
    recordOutcome('failed');
    return NextResponse.json(
      { error: 'The reviewed Automation revision is no longer available.' },
      { status: 404, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  if (!inspection.preflight.ok) {
    recordOutcome('denied');
    return NextResponse.json(
      { error: 'Security or schema errors must be resolved before download.', preflight: inspection.preflight },
      { status: 422, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  try {
    const bundle = buildDisabledAutomationBundle(inspection.preflight, {
      acknowledgeWarnings: body.acknowledgeWarnings === true,
    });
    let emitted = false;
    const responseBody = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (emitted) return;
        emitted = true;
        controller.enqueue(new TextEncoder().encode(bundle));
        controller.close();
        recordOutcome('success');
      },
      cancel() {
        recordOutcome('cancelled');
      },
    });
    return new NextResponse(responseBody, {
      status: 200,
      headers: {
        'Cache-Control': 'no-store',
        'Content-Type': 'application/toml; charset=utf-8',
        'Content-Disposition': `attachment; filename="${safeFileStem(repo)}-automation.toml"`,
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch {
    recordOutcome('denied');
    return NextResponse.json(
      { error: 'Review and acknowledge every warning before download.' },
      { status: 409, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
