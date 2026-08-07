import { NextRequest, NextResponse } from 'next/server';
import { forgejoBrowserSession } from '@/lib/forgejo-session';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const session = await forgejoBrowserSession(request.headers.get('cookie') || '');
  return NextResponse.json(session, {
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
}

