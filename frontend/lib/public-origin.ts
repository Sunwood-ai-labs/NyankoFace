const PRIVATE_SERVICE_HOSTS = new Set([
  'forgejo',
  'frontend',
  'gateway',
  'nyankoface-mcp',
  'spaces-runner',
]);

function parseIpv6Groups(host: string): number[] | undefined {
  if (!host.includes(':')) return undefined;
  const sections = host.split('::');
  if (sections.length > 2) return undefined;
  const left = sections[0] ? sections[0].split(':') : [];
  const right = sections.length === 2 && sections[1] ? sections[1].split(':') : [];
  if (
    left.some((part) => !/^[0-9a-f]{1,4}$/i.test(part)) ||
    right.some((part) => !/^[0-9a-f]{1,4}$/i.test(part))
  ) return undefined;
  if (sections.length === 1 && left.length !== 8) return undefined;
  const missing = 8 - left.length - right.length;
  if (sections.length === 2 && missing < 1) return undefined;
  return [
    ...left.map((part) => Number.parseInt(part, 16)),
    ...(sections.length === 2 ? Array.from({ length: missing }, () => 0) : []),
    ...right.map((part) => Number.parseInt(part, 16)),
  ];
}

function isNonGlobalIpv6(host: string): boolean {
  const groups = parseIpv6Groups(host);
  if (!groups) return false;
  const [first, second] = groups;
  return (
    first === 0 ||
    (first >= 0xfc00 && first <= 0xfdff) ||
    (first >= 0xfe80 && first <= 0xfebf) ||
    (first >= 0xfec0 && first <= 0xfeff) ||
    (first >= 0xff00 && first <= 0xffff) ||
    (first === 0x100 && groups[1] === 0 && groups[2] === 0 && groups[3] === 0) ||
    (first === 0x2001 && [0, 2, 0x10, 0x20, 0xdb8].includes(second))
  );
}

function isNonGlobalIpv4(host: string): boolean {
  const octets = host.split('.').map((part) => Number(part));
  if (
    octets.length !== 4 ||
    octets.some((part) => !Number.isInteger(part) || part < 0 || part > 255)
  ) return false;
  const [first, second, third, fourth] = octets;
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    (first === 100 && second >= 64 && second <= 127) ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 0 && third === 0 && fourth !== 9 && fourth !== 10) ||
    (first === 192 && second === 0 && third === 2) ||
    (first === 192 && second === 88 && third === 99) ||
    (first === 192 && second === 168) ||
    (first === 198 && second >= 18 && second <= 19) ||
    (first === 198 && second === 51 && third === 100) ||
    (first === 203 && second === 0 && third === 113) ||
    first >= 224
  );
}

export function isPrivateHostname(hostname: string): boolean {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  if (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    host.endsWith('.lan') ||
    host.endsWith('.home') ||
    host.endsWith('.home.arpa') ||
    host.endsWith('.corp') ||
    host.endsWith('.intranet') ||
    host.endsWith('.private') ||
    host.endsWith('.svc') ||
    host.endsWith('.cluster.local') ||
    host.endsWith('.test') ||
    (!host.includes('.') && !host.includes(':')) ||
    PRIVATE_SERVICE_HOSTS.has(host)
  ) return true;
  if (isNonGlobalIpv4(host)) return true;
  if (host === '::1' || host === '::' || host === '0.0.0.0') return true;
  const mappedIpv4 = ipv4FromMappedIpv6(host);
  return mappedIpv4 ? isPrivateHostname(mappedIpv4) : isNonGlobalIpv6(host);
}

function ipv4FromMappedIpv6(host: string): string | undefined {
  if (!host.includes(':')) return undefined;
  const halves = host.split('::');
  if (halves.length > 2) return undefined;
  const left = halves[0] ? halves[0].split(':') : [];
  const right = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  if (left.some((part) => !/^[0-9a-f]{1,4}$/i.test(part)) || right.some((part) => !/^[0-9a-f]{1,4}$/i.test(part))) {
    return undefined;
  }
  const groups = halves.length === 2
    ? [...left, ...Array.from({ length: 8 - left.length - right.length }, () => '0'), ...right]
    : [...left];
  if (groups.length !== 8 || groups.slice(0, 5).some((part) => part !== '0') || groups[5].toLowerCase() !== 'ffff') {
    return undefined;
  }
  const high = Number.parseInt(groups[6], 16);
  const low = Number.parseInt(groups[7], 16);
  return [high >> 8, high & 0xff, low >> 8, low & 0xff].join('.');
}

function parseHttpUrl(value: unknown, allowQueryAndFragment = true): URL | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  if (value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) return undefined;
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
  if (trimmed.includes('\\') || /[\u0000-\u001f\u007f]/.test(trimmed)) return undefined;
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
  if (headers.get('x-nyankoface-trusted-host')?.trim() !== '1') return undefined;
  const host = headers.get('host')?.trim();
  const protocol = headers.get('x-forwarded-proto')?.split(',')[0]?.trim() || 'https';
  if (!host || (protocol !== 'http' && protocol !== 'https') || host.length > 255 || /[\\/?#@\s,]/.test(host)) return undefined;
  try {
    const parsed = new URL(`${protocol}://${host}`);
    if (parsed.pathname !== '/' || parsed.search || parsed.hash || parsed.username || parsed.password) return undefined;
    return parsed.origin;
  } catch {
    return undefined;
  }
}

/** Prefer the configured public origin, then the origin observed at the gateway. */
export function resolvePublicOrigin(configured: unknown, requestOrigin: unknown): string | undefined {
  const configuredPublic = safePublicOrigin(configured);
  if (configuredPublic) return configuredPublic;
  const requestPublic = safePublicOrigin(requestOrigin);
  if (requestPublic) return requestPublic;
  return undefined;
}

export function shareablePublicUrl(value: unknown, origin?: string): string | undefined {
  const safe = sanitizePublicUrl(value);
  if (!safe || !safe.startsWith('/')) return safe;
  const browserOrigin = origin || (typeof window !== 'undefined' ? window.location.origin : undefined);
  if (!browserOrigin) return undefined;
  try {
    return new URL(safe, browserOrigin).href;
  } catch {
    return safe;
  }
}

function sanitizePublicText(value: string): string {
  return value.replace(/(?:https?:[\\/]+|[\\/]{2})[^\s<>"'`]+/gi, (candidate) => {
    const trailing = candidate.match(/[),.;!?]+$/)?.[0] || '';
    const url = trailing ? candidate.slice(0, -trailing.length) : candidate;
    const safe = sanitizePublicUrl(url);
    return `${safe || '[internal URL omitted]'}${trailing}`;
  });
}

function sanitizePublicValue(value: unknown): unknown {
  if (typeof value === 'string') {
    const direct = sanitizePublicUrl(value);
    return direct ?? sanitizePublicText(value);
  }
  if (Array.isArray(value)) return value.map((item) => sanitizePublicValue(item));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, sanitizePublicValue(entry)]),
  );
}

export function sanitizePublicUrlRecord(value: unknown): unknown {
  return sanitizePublicValue(value);
}

export function sanitizePublicUrlJson(body: string): string {
  try {
    return JSON.stringify(sanitizePublicUrlRecord(JSON.parse(body)));
  } catch {
    return JSON.stringify({ error: 'Upstream response was not valid JSON.' });
  }
}
