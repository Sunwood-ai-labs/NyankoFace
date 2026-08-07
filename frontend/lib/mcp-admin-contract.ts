import { createHmac, timingSafeEqual } from 'node:crypto';
import { SERVICE_ACCOUNT_ID_PATTERN_SOURCE } from './mcp-admin-ui';

export type AdminSession = {
  authenticated: boolean;
  username?: string;
  isAdmin?: boolean;
};

const ROUTES = [
  /^reauth$/,
  /^state$/,
  /^service-accounts$/,
  new RegExp(`^service-accounts/${SERVICE_ACCOUNT_ID_PATTERN_SOURCE}/(?:disable|remap)$`),
  /^tokens$/,
  /^tokens\/[a-zA-Z0-9-]{1,128}\/(?:rotate|revoke)$/,
  /^policies$/,
  /^connection-tests$/,
];

export const REAUTH_MAX_AGE_SECONDS = 300;
export const FORGEJO_FETCH_TIMEOUT_MS = 10_000;
export const ADMIN_BFF_TIMEOUT_MS = 35_000;
export const ADMIN_MAX_BODY_BYTES = 65_536;

export function isSecureAdminTransport(
  headers: { get(name: string): string | null },
  requestUrl?: string,
): boolean {
  const forwardedProto = headers.get('x-forwarded-proto')
    ?.split(',', 1)[0]
    ?.trim()
    .toLowerCase();
  if (forwardedProto) return forwardedProto === 'https';
  if (!requestUrl) return false;
  try {
    return new URL(requestUrl).protocol === 'https:';
  } catch {
    return false;
  }
}

export type BoundedRequestBodyResult =
  | { body: string; bytes: number }
  | { error: 'invalid' | 'timeout' | 'too_large' };

export function remainingDeadline(deadline: number, now = Date.now()): number {
  return Math.max(0, deadline - now);
}

export async function boundedForgejoFetch(
  fetcher: typeof fetch,
  input: string,
  init: RequestInit,
  timeoutMs = FORGEJO_FETCH_TIMEOUT_MS,
): Promise<Response | null> {
  if (timeoutMs <= 0) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetcher(input, { ...init, signal: controller.signal });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function boundedForgejoFetchAndRead<T>(
  fetcher: typeof fetch,
  input: string,
  init: RequestInit,
  reader: (response: Response) => Promise<T>,
  timeoutMs = FORGEJO_FETCH_TIMEOUT_MS,
): Promise<{ response: Response; value: T } | null> {
  if (timeoutMs <= 0) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(input, { ...init, signal: controller.signal });
    return { response, value: await reader(response) };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function readBoundedRequestBody(
  body: ReadableStream<Uint8Array> | null,
  timeoutMs: number,
  maxBytes = ADMIN_MAX_BODY_BYTES,
): Promise<BoundedRequestBodyResult> {
  if (!body) return { body: '', bytes: 0 };
  if (timeoutMs <= 0) return { error: 'timeout' };
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let value = '';
  let bytes = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const consume = (async (): Promise<BoundedRequestBodyResult> => {
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) {
          value += decoder.decode();
          return { body: value, bytes };
        }
        if (!chunk.value) continue;
        bytes += chunk.value.byteLength;
        if (bytes > maxBytes) {
          void reader.cancel().catch(() => undefined);
          return { error: 'too_large' };
        }
        value += decoder.decode(chunk.value, { stream: true });
      }
    } catch {
      return { error: 'invalid' };
    }
  })();
  const deadline = new Promise<BoundedRequestBodyResult>((resolve) => {
    timer = setTimeout(() => {
      void reader.cancel().catch(() => undefined);
      resolve({ error: 'timeout' });
    }, timeoutMs);
  });
  try {
    return await Promise.race([consume, deadline]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function sign(value: string, secret: string): string {
  return createHmac('sha256', secret).update(value).digest('base64url');
}

export function namedCookie(header: string, name: string): string | null {
  for (const item of header.split(';')) {
    const [key, ...parts] = item.trim().split('=');
    if (key === name) return parts.join('=') || null;
  }
  return null;
}

export function issueReauthProof(
  subject: string,
  sessionId: string,
  secret: string,
  authenticatedAt: number,
): string {
  const binding = sign(`session\0${sessionId}`, secret);
  const payload = Buffer.from(JSON.stringify({ version: 1, subject, binding, authenticatedAt }))
    .toString('base64url');
  return `${payload}.${sign(`proof\0${payload}`, secret)}`;
}

export function verifyReauthProof(
  proof: string | null,
  subject: string,
  sessionId: string | null,
  secret: string,
  now: number,
): number | null {
  if (!proof || !sessionId) return null;
  const [payload, suppliedSignature, extra] = proof.split('.');
  if (!payload || !suppliedSignature || extra) return null;
  const expectedSignature = sign(`proof\0${payload}`, secret);
  const supplied = Buffer.from(suppliedSignature);
  const expected = Buffer.from(expectedSignature);
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return null;
  try {
    const value = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as Record<string, unknown>;
    const authenticatedAt = Number(value.authenticatedAt);
    const expectedBinding = sign(`session\0${sessionId}`, secret);
    if (value.version !== 1 || value.subject !== subject || value.binding !== expectedBinding
      || !Number.isInteger(authenticatedAt) || authenticatedAt > now
      || now - authenticatedAt > REAUTH_MAX_AGE_SECONDS) return null;
    return authenticatedAt;
  } catch {
    return null;
  }
}

const FORBIDDEN_KEYS = new Set([
  'token_sha256', 'forgejo_token_file', 'idempotency_fingerprint',
  'previous_hash', 'event_hash',
]);

export function adminSubject(session: AdminSession): string | null {
  return session.authenticated && session.isAdmin && session.username
    ? `human:${session.username}`
    : null;
}

export function safeAdminRoute(segments: string[]): string | null {
  const route = segments.join('/');
  return ROUTES.some((pattern) => pattern.test(route)) ? route : null;
}

export function sanitizeAdminPayload(value: unknown, allowOneTimeToken = false): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeAdminPayload(item, false));
  }
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    if (FORBIDDEN_KEYS.has(key)) return [];
    if (key === 'token' && !allowOneTimeToken) return [];
    return [[key, sanitizeAdminPayload(item, false)]];
  }));
}
