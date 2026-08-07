import { NextRequest, NextResponse } from 'next/server';
import { inspectPublicAutomationRepository } from '@/lib/automation-repository';

export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const ref = request.nextUrl.searchParams.get('ref')?.trim() || undefined;
  const inspection = await inspectPublicAutomationRepository(owner, repo, ref);
  if (!inspection) {
    return NextResponse.json(
      { error: 'Public Automation repository or automation.toml was not found.' },
      { status: 404, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  return NextResponse.json(inspection.preflight, {
    headers: { 'Cache-Control': 'no-store' },
  });
}
