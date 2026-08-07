import { NextRequest, NextResponse } from 'next/server';

function searchTarget(rawQuery: string) {
  const query = rawQuery.trim();
  const strip = (pattern: RegExp) => query.replace(pattern, '').trim();
  if (/^datasets?:/i.test(query)) return { path: '/datasets', query: strip(/^datasets?:\s*/i) };
  if (/^spaces?:/i.test(query)) return { path: '/spaces', query: strip(/^spaces?:\s*/i) };
  if (/^characters?:/i.test(query)) return { path: '/characters', query: strip(/^characters?:\s*/i) };
  if (/^benchmarks?:/i.test(query)) return { path: '/benchmarks', query: strip(/^benchmarks?:\s*/i) };
  if (/^automations?:/i.test(query)) return { path: '/automations', query: strip(/^automations?:\s*/i) };
  if (/^users?:/i.test(query)) return { path: '/git/explore/users', query: strip(/^users?:\s*/i) };
  if (/^repos?:/i.test(query)) return { path: '/git/explore/repos', query: strip(/^repos?:\s*/i) };
  return { path: '/models', query };
}

export function GET(request: NextRequest) {
  const target = searchTarget(request.nextUrl.searchParams.get('q') || '');
  const forwardedHost = request.headers.get('x-forwarded-host') || request.headers.get('host') || request.nextUrl.host;
  const forwardedProto = request.headers.get('x-forwarded-proto') || request.nextUrl.protocol.replace(':', '') || 'http';
  const url = new URL(`${forwardedProto}://${forwardedHost}`);
  url.pathname = target.path;
  url.search = target.query ? `?q=${encodeURIComponent(target.query)}` : '';
  return NextResponse.redirect(url);
}
