const PRIVATE_SERVICE_HOSTS = new Set([
  'forgejo',
  'frontend',
  'gateway',
  'nyankoface-mcp',
  'spaces-runner',
]);

export function isPrivateHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    host.endsWith('.lan') ||
    host.endsWith('.home') ||
    PRIVATE_SERVICE_HOSTS.has(host)
  ) return true;
  if (/^(?:10|127)\.(?:\d{1,3}\.){2}\d{1,3}$/.test(host)) return true;
  if (/^169\.254\.(?:\d{1,3}\.)\d{1,3}$/.test(host)) return true;
  if (/^192\.168\.(?:\d{1,3}\.)\d{1,3}$/.test(host)) return true;
  if (/^100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.(?:\d{1,3}\.)\d{1,3}$/.test(host)) return true;
  const private172 = host.match(/^172\.(\d{1,3})\.(?:\d{1,3}\.)\d{1,3}$/);
  if (private172 && Number(private172[1]) >= 16 && Number(private172[1]) <= 31) return true;
  if (host === '::1' || host === '::' || host === '0.0.0.0') return true;
  if (/^f[cd][0-9a-f:]*$/i.test(host) || /^fe[89ab][0-9a-f:]*$/i.test(host)) return true;
  return /^::ffff:(?:10\.|127\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/i.test(host);
}

function parseHttpUrl(value: unknown, allowQueryAndFragment = true): URL | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    if (url.username || url.password) return undefined;
    if (!allowQueryAndFragment && (url.search || url.hash)) return undefined;
    return url;
  } catch {
    return undefined;
  }
}

/** Convert internal absolute links to safe same-origin paths. */
export function sanitizePublicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed;
  const url = parseHttpUrl(trimmed);
  if (!url) return undefined;
  if (isPrivateHostname(url.hostname)) {
    return `${url.pathname || '/'}${url.search}${url.hash}`;
  }
  return url.href;
}

function safePublicOrigin(value: unknown): string | undefined {
  const url = parseHttpUrl(value, false);
  if (!url) return undefined;
  if (isPrivateHostname(url.hostname)) {
    return undefined;
  }
  return url.href.replace(/\/$/, '');
}

export function requestOriginFromHeaders(headers: { get(name: string): string | null }): string | undefined {
  const host = headers.get('x-forwarded-host')?.split(',')[0]?.trim() || headers.get('host')?.trim();
  const protocol = headers.get('x-forwarded-proto')?.split(',')[0]?.trim() || 'https';
  if (!host || (protocol !== 'http' && protocol !== 'https') || host.includes('/')) return undefined;
  return `${protocol}://${host}`;
}

/** Prefer the configured public origin, then the origin observed at the gateway. */
export function resolvePublicOrigin(configured: unknown, requestOrigin: unknown): string | undefined {
  const configuredPublic = safePublicOrigin(configured);
  if (configuredPublic) return configuredPublic;
  const requestPublic = safePublicOrigin(requestOrigin);
  if (requestPublic) return requestPublic;
  return undefined;
}

export function sanitizePublicUrlRecord(value: unknown): unknown {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
  const record = value as Record<string, unknown>;
  if (!Object.prototype.hasOwnProperty.call(record, 'public_url')) return value;
  return { ...record, public_url: sanitizePublicUrl(record.public_url) || null };
}

export function sanitizePublicUrlJson(body: string): string {
  try {
    return JSON.stringify(sanitizePublicUrlRecord(JSON.parse(body)));
  } catch {
    return body;
  }
}
