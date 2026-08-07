import 'server-only';

import { readFile } from 'node:fs/promises';
import { ForgejoUnavailable, forgejoBrowserSession, verifyForgejoPassword } from './forgejo-session';
import {
  adminSubject,
  ADMIN_MAX_BODY_BYTES,
  ADMIN_BFF_TIMEOUT_MS,
  issueReauthProof,
  isSecureAdminTransport,
  namedCookie,
  readBoundedRequestBody,
  remainingDeadline,
  safeAdminRoute,
  sanitizeAdminPayload,
  verifyReauthProof,
} from './mcp-admin-contract';

const ADMIN_URL = (process.env.NYANKOFACE_MCP_ADMIN_URL || 'http://mcp-admin:8001').replace(/\/$/, '');
const TOKEN_FILE = process.env.NYANKOFACE_MCP_ADMIN_INTERNAL_TOKEN_FILE
  || '/run/secrets/nyankoface-mcp-admin-internal-token';
const NO_STORE = { 'Cache-Control': 'private, no-store, max-age=0', Pragma: 'no-cache' };
const FORGEJO_SESSION_COOKIE = 'nyankoface_session';
const REAUTH_COOKIE = 'nyankoface_mcp_reauth';

function json(payload: unknown, status: number, headers: Record<string, string> = {}) {
  return Response.json(payload, { status, headers: { ...NO_STORE, ...headers } });
}

export async function proxyMcpAdmin(request: Request, segments: string[]): Promise<Response> {
  if (!isSecureAdminTransport(request.headers, request.url)) {
    return json({ error: 'https_required' }, 426, { Vary: 'X-Forwarded-Proto' });
  }
  const deadline = Date.now() + ADMIN_BFF_TIMEOUT_MS;
  const route = safeAdminRoute(segments);
  if (!route) return json({ error: 'not_found' }, 404);

  const cookieHeader = request.headers.get('cookie') || '';
  const forgejoSessionId = namedCookie(cookieHeader, FORGEJO_SESSION_COOKIE);
  const forgejoCookie = forgejoSessionId
    ? `${FORGEJO_SESSION_COOKIE}=${forgejoSessionId}`
    : '';
  let session;
  try {
    session = await forgejoBrowserSession(forgejoCookie, remainingDeadline(deadline), { failClosed: true });
  } catch (error) {
    if (error instanceof ForgejoUnavailable) return json({ error: 'forgejo_unavailable' }, 503);
    return json({ error: 'admin_backend_unavailable' }, 503);
  }
  const subject = adminSubject(session);
  if (!subject) {
    return json({ error: session.authenticated ? 'forbidden' : 'unauthorized' },
      session.authenticated ? 403 : 401);
  }

  let internalToken: string;
  try {
    internalToken = (await readFile(TOKEN_FILE, 'utf-8')).trim();
    if (internalToken.length < 32) throw new Error('invalid');
  } catch {
    return json({ error: 'admin_backend_unavailable' }, 503);
  }

  const source = new URL(request.url);
  const upstream = new URL(`/v1/${route}${source.search}`, ADMIN_URL);
  const method = request.method.toUpperCase();
  const hasBody = !['GET', 'HEAD'].includes(method);
  const declaredLength = Number(request.headers.get('content-length') || '0');
  if (!Number.isFinite(declaredLength) || declaredLength > ADMIN_MAX_BODY_BYTES) {
    return json({ error: 'request_too_large' }, 413);
  }
  const bodyResult = hasBody
    ? await readBoundedRequestBody(request.body, remainingDeadline(deadline))
    : { body: '', bytes: 0 };
  if ('error' in bodyResult) {
    const status = bodyResult.error === 'too_large' ? 413 : bodyResult.error === 'timeout' ? 408 : 400;
    return json({ error: bodyResult.error === 'too_large' ? 'request_too_large' : 'invalid_request_body' }, status);
  }
  const body = hasBody ? bodyResult.body : undefined;
  if (route === 'reauth') {
    if (method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
    let password = '';
    let otp = '';
    try {
      const payload = JSON.parse(body || '{}') as { password?: unknown; otp?: unknown };
      password = typeof payload.password === 'string' ? payload.password : '';
      otp = typeof payload.otp === 'string' ? payload.otp.trim() : '';
    } catch {
      otp = '';
      return json({ error: 'invalid_json' }, 400);
    }
    let verified = false;
    try {
      verified = Boolean(session.username && forgejoSessionId)
        && await verifyForgejoPassword(session.username!, password, otp, remainingDeadline(deadline));
    } catch (error) {
      password = '';
      otp = '';
      if (error instanceof ForgejoUnavailable) return json({ error: 'forgejo_unavailable' }, 503);
      return json({ error: 'admin_backend_unavailable' }, 503);
    }
    password = '';
    otp = '';
    if (!verified) return json({ error: 'reauthentication_failed' }, 401);
    const authenticatedAt = Math.floor(Date.now() / 1000);
    const proof = issueReauthProof(subject, forgejoSessionId!, internalToken, authenticatedAt);
    return json({ ok: true }, 200, {
      'Set-Cookie': `${REAUTH_COOKIE}=${proof}; Max-Age=300; Path=/api/admin/mcp; HttpOnly; Secure; SameSite=Strict`,
    });
  }
  const reauthenticatedAt = verifyReauthProof(
    namedCookie(cookieHeader, REAUTH_COOKIE),
    subject,
    forgejoSessionId,
    internalToken,
    Math.floor(Date.now() / 1000),
  );
  if (reauthenticatedAt === null) {
    return json({ error: 'fresh_reauthentication_required' }, 428, {
      'Set-Cookie': `${REAUTH_COOKIE}=; Max-Age=0; Path=/api/admin/mcp; HttpOnly; Secure; SameSite=Strict`,
    });
  }
  let response: Response;
  try {
    response = await fetch(upstream, {
      method,
      headers: {
        Authorization: `Bearer ${internalToken}`,
        'X-NyankoFace-Admin-Subject': subject,
        'X-NyankoFace-Admin-Reauthenticated-At': String(reauthenticatedAt),
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
      },
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(remainingDeadline(deadline)),
    });
  } catch {
    return json({ error: 'admin_backend_unavailable' }, 503);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return json({ error: 'invalid_admin_response' }, 502);
  }
  const oneTime = method === 'POST'
    && (route === 'tokens' || /^tokens\/[^/]+\/rotate$/.test(route))
    && response.ok;
  return json(sanitizeAdminPayload(payload, oneTime), response.status);
}
