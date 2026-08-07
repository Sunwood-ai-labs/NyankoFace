import { NextRequest, NextResponse } from 'next/server';
import {
  consumeNavigationRateLimit,
  NavigationRateBucket,
  NAVIGATION_RATE_LIMIT_CLIENTS,
  pruneExpiredNavigationRateLimits,
  NAVIGATION_ROUTE_CLASSES,
  NavigationRouteClass,
  NavigationSample,
  normalizeNavigationSample,
  summarizeNavigationSamples,
} from '@/lib/navigation-performance';

export const dynamic = 'force-dynamic';

const MAX_SAMPLES_PER_ROUTE = 200;
const MAX_SAMPLE_BODY_BYTES = 2_048;
const globalMetrics = globalThis as typeof globalThis & {
  __nyankofaceNavigationSamples?: Map<NavigationRouteClass, NavigationSample[]>;
  __nyankofaceNavigationRateLimits?: Map<string, NavigationRateBucket>;
};
const samplesByRoute = globalMetrics.__nyankofaceNavigationSamples
  ?? new Map<NavigationRouteClass, NavigationSample[]>();
globalMetrics.__nyankofaceNavigationSamples = samplesByRoute;
const rateLimits = globalMetrics.__nyankofaceNavigationRateLimits ?? new Map<string, NavigationRateBucket>();
globalMetrics.__nyankofaceNavigationRateLimits = rateLimits;

function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get('origin');
  if (!origin || request.headers.get('sec-fetch-site') !== 'same-origin') return false;
  try {
    const originUrl = new URL(origin);
    const host = (request.headers.get('x-forwarded-host') || request.headers.get('host') || '')
      .split(',')[0]
      .trim();
    const protocol = (request.headers.get('x-forwarded-proto') || request.nextUrl.protocol)
      .split(',')[0]
      .trim()
      .replace(/:$/, '');
    return originUrl.host === host && originUrl.protocol === `${protocol}:`;
  } catch {
    return false;
  }
}

function clientKey(request: NextRequest): string {
  return request.headers.get('x-real-ip') || 'local-direct-client';
}

async function readBoundedBody(request: NextRequest): Promise<string | null> {
  const declaredLength = request.headers.get('content-length');
  if (declaredLength) {
    const parsedLength = Number.parseInt(declaredLength, 10);
    if (!Number.isFinite(parsedLength) || parsedLength < 0 || parsedLength > MAX_SAMPLE_BODY_BYTES) return null;
  }
  if (!request.body) return '';
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let received = 0;
  let body = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value.byteLength;
    if (received > MAX_SAMPLE_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin metrics are not accepted.' }, { status: 403 });
  }
  let payload: unknown;
  try {
    const body = await readBoundedBody(request);
    if (body === null) {
      return NextResponse.json({ error: 'Navigation sample is too large.' }, { status: 413 });
    }
    payload = JSON.parse(body);
  } catch {
    return NextResponse.json({ error: 'Invalid JSON.' }, { status: 400 });
  }
  const sample = normalizeNavigationSample(payload);
  if (!sample) {
    return NextResponse.json({ error: 'Invalid navigation sample.' }, { status: 400 });
  }
  const key = clientKey(request);
  const now = Date.now();
  if (!rateLimits.has(key) && rateLimits.size >= NAVIGATION_RATE_LIMIT_CLIENTS) {
    pruneExpiredNavigationRateLimits(rateLimits, now);
    if (rateLimits.size >= NAVIGATION_RATE_LIMIT_CLIENTS) {
      return NextResponse.json(
        { error: 'Navigation telemetry client capacity exceeded.' },
        { status: 429, headers: { 'Retry-After': '60' } },
      );
    }
  }
  const rate = consumeNavigationRateLimit(rateLimits.get(key), now);
  rateLimits.set(key, rate.bucket);
  if (!rate.allowed) {
    return NextResponse.json(
      { error: 'Navigation sample rate limit exceeded.' },
      { status: 429, headers: { 'Retry-After': '60' } },
    );
  }
  const samples = samplesByRoute.get(sample.route) ?? [];
  samples.push(sample);
  if (samples.length > MAX_SAMPLES_PER_ROUTE) {
    samples.splice(0, samples.length - MAX_SAMPLES_PER_ROUTE);
  }
  samplesByRoute.set(sample.route, samples);
  return new NextResponse(null, { status: 202 });
}

export async function GET() {
  const summaries = NAVIGATION_ROUTE_CLASSES
    .map((route) => summarizeNavigationSamples(route, samplesByRoute.get(route) ?? []))
    .filter((summary) => summary.count > 0)
    .sort((left, right) => right.p95Ms - left.p95Ms || right.count - left.count);
  return NextResponse.json(
    { generatedAt: new Date().toISOString(), maxSamplesPerRoute: MAX_SAMPLES_PER_ROUTE, routes: summaries },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
