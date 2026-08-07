import { NextRequest, NextResponse } from 'next/server';
import { forgejoLogout } from '@/lib/forgejo-session';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const response = await forgejoLogout(request.headers.get('cookie') || '');
  if (!response) {
    return NextResponse.json({ authenticated: false }, { status: 200 });
  }

  const result = NextResponse.json({ authenticated: false }, {
    status: response.ok || response.status === 303 ? 200 : response.status,
    headers: { 'Cache-Control': 'private, no-store, max-age=0' },
  });
  const setCookie = response.headers.get('set-cookie');
  if (setCookie) result.headers.set('set-cookie', setCookie);
  return result;
}

