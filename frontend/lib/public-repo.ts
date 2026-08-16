import { isPrivateHostname as isNonPublicHostname } from './public-origin';
import type { Repo } from './forgejo';

const UPSTREAM_URL_FIELDS = [
  'url',
  'clone_url',
  'ssh_url',
  'mirror_url',
  'original_url',
  'website',
] as const;

const NESTED_URL_PATTERNS = [
  /(?<![a-z0-9+.-])(?=([a-z][a-z0-9+.-]*:[\\/]{1,3}[^\s<>"'`&]+))/gi,
  /(?<![a-z0-9+.-])(?=(https?:[^\s<>"'`&]*?(?::\d{1,5}|\/)[^\s<>"'`&]*))/gi,
  /(?<!:)(?=(\/[\/][^\s<>"'`&]+))/gi,
  /(?=(\b[\w.-]+@(?:[a-z0-9.-]+|\[[0-9a-f:.]+\]):[^\s<>"'`&]+))/gi,
];
const MAX_URL_DECODE_PASSES = 8;
const ISO_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/;
const PRIVATE_BARE_HOSTS = new Set([
  'backend',
  'dependency-stub',
  'forgejo',
  'forgejo-actions-dind',
  'forgejo-actions-runner',
  'frontend',
  'gateway',
  'git',
  'gitea',
  'gpu-worker',
  'fixture',
  'localhost',
  'maintenance-agent',
  'mcp',
  'mcp-a',
  'mcp-b',
  'mcp-admin',
  'nyankoface',
  'nyankoface-mcp',
  'probe',
  'postgres',
  'seed',
  'spaces-runner',
]);

function configuredForgejoHostname(): string | undefined {
  const configured = process.env.FORGEJO_API;
  if (!configured) return undefined;
  try {
    return new URL(configured).hostname
      .toLowerCase()
      .replace(/^\[|\]$/g, '')
      .replace(/\.+$/, '');
  } catch {
    return undefined;
  }
}

function isPrivateHostname(hostname: string): boolean {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  return configuredForgejoHostname() === host || isNonPublicHostname(host);
}

function canonicalNumericIpv4Host(hostname: string, port?: string): string | undefined {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  const isDottedNumeric = /^[0-9a-fx]+(?:\.[0-9a-fx]+){1,3}$/i.test(host);
  const isHexNumeric = /^0x[0-9a-f]+$/i.test(host);
  const isLongDecimal = /^\d{4,}$/.test(host);
  const isShortDecimalEndpoint = /^\d{1,3}$/.test(host) && (port !== undefined || host.length === 3);
  // A short decimal token such as the `12` in `12:30` is ordinary text;
  // the caller excludes clock-shaped tokens while host-and-port syntax,
  // long decimal, and dotted/hex forms are accepted numeric IPv4 spellings
  // by WHATWG URL parsing.
  if (!isDottedNumeric && !isHexNumeric && !isLongDecimal && !isShortDecimalEndpoint) return undefined;
  try {
    const parsed = new URL(`http://${host}/`).hostname.replace(/^\[|\]$/g, '');
    return /^\d+\.\d+\.\d+\.\d+$/.test(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function isEstablishedPrivateEndpointHost(hostname: string, port?: string): boolean {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  if (configuredForgejoHostname() === host || PRIVATE_BARE_HOSTS.has(host)) return true;
  const canonicalNumericHost = canonicalNumericIpv4Host(host, port);
  if (canonicalNumericHost && isPrivateHostname(canonicalNumericHost)) return true;
  return (host.includes('.') || host.includes(':')) && isPrivateHostname(host);
}

function containsUnsafeNestedUrl(value: string): boolean {
  let current = value;
  for (let pass = 0; pass < MAX_URL_DECODE_PASSES; pass += 1) {
    for (const pattern of NESTED_URL_PATTERNS) {
      for (const match of current.matchAll(pattern)) {
        const candidate = (match[1] || '').replace(/[),.;!?]+$/, '');
        if (
          candidate.startsWith('//') &&
          match.index > 0 &&
          !/[?&#=\s([{<]/.test(current[match.index - 1])
        ) continue;
        try {
          const nested = new URL(candidate);
          const slashlessHttpTarget = /^https?:[^\\/]/i.test(candidate);
          const unsafeHost = slashlessHttpTarget
            ? isEstablishedPrivateEndpointHost(nested.hostname)
            : isPrivateHostname(nested.hostname);
          if (
            (nested.protocol !== 'http:' && nested.protocol !== 'https:') ||
            nested.username ||
            nested.password ||
            unsafeHost
          ) return true;
        } catch {
          return true;
        }
      }
    }
    let decoded: string;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      return true;
    }
    if (decoded === current) break;
    current = decoded;
  }
  // A value that still changes after the bounded decode budget is ambiguous;
  // do not preserve it at a public metadata boundary.
  try {
    return decodeURIComponent(current) !== current;
  } catch {
    return true;
  }
}

export function safePublicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (trimmed.includes('\\') || /[\u0000-\u001f\u007f]/.test(trimmed)) return undefined;
  // A protocol-relative URL such as //forgejo:3000/... is not a safe
  // root-relative path; browsers resolve it against the current scheme.
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) {
    return containsUnsafeNestedUrl(trimmed) ? undefined : trimmed;
  }
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    if (url.username || url.password) return undefined;
    if (containsUnsafeNestedUrl(`${url.pathname}${url.search}${url.hash}`)) return undefined;
    return isPrivateHostname(url.hostname) ? undefined : url.href;
  } catch {
    return undefined;
  }
}

function stripNestedUrlFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripNestedUrlFields);
  if (!value || typeof value !== 'object') return value;
  const result: Record<string, unknown> = {};
  for (const [key, nested] of Object.entries(value)) {
    if (
      key === 'url' ||
      key.endsWith('_url') ||
      key === 'website' ||
      key === 'external_tracker' ||
      key === 'external_tracker_format'
    ) continue;
    result[key] = stripNestedUrlFields(nested);
  }
  return result;
}

function sanitizePublicRepoTextOnce(value: string): string {
  const scrub = (candidate: string): string => {
    const trailing = candidate.match(/[),.;!?]+$/)?.[0] || '';
    const url = trailing ? candidate.slice(0, -trailing.length) : candidate;
    const safe = safePublicUrl(url);
    return `${safe || '[internal URL omitted]'}${trailing}`;
  };
  const scrubBareEndpoint = (candidate: string): string => {
    const endpoint = candidate.match(/^((?:[a-z0-9.-]+|\[[0-9a-f:.]+\])):(\d{1,5})(?:[/?#][^\s<>"'`]*)?$/i);
    if (!endpoint) return candidate;
    const host = endpoint[1];
    const port = endpoint[2];
    if (!candidate.includes('/') && !candidate.includes('?') && !candidate.includes('#') && /^(?:[01]?\d|2[0-3]):[0-5]\d\b/.test(candidate)) {
      return candidate;
    }
    return isEstablishedPrivateEndpointHost(host, port) ? '[internal URL omitted]' : candidate;
  };
  const scrubUsernameLessScpEndpoint = (candidate: string): string => {
    const numericHostPort = candidate.match(/^(\d{1,3}):(\d{1,5})(?=[/?#])/);
    if (numericHostPort && isEstablishedPrivateEndpointHost(numericHostPort[1], numericHostPort[2])) {
      return '[internal URL omitted]';
    }
    const host = candidate.startsWith('[')
      ? candidate.slice(0, candidate.indexOf(']') + 1)
      : candidate.slice(0, candidate.indexOf(':'));
    return isEstablishedPrivateEndpointHost(host) ? '[internal URL omitted]' : candidate;
  };
  return value
    .replace(/(?!(?:[a-z]:[\\/]))(?:[a-z][a-z0-9+.-]*:[\\/]{1,3}|[\\/]{2})[^\s<>"'`]+/gi, scrub)
    .replace(/\b[\w.-]+@(?:[a-z0-9.-]+|\[[0-9a-f:.]+\]):[^\s<>"'`]+/gi, scrub)
    .replace(/(?<![a-z0-9.-])(?:[a-z0-9.-]+|\[[0-9a-f:.]+\]):[^\s<>"'`]*\/[^\s<>"'`]+/gi, scrubUsernameLessScpEndpoint)
    .replace(/(?<![a-z0-9.-])(?:[a-z0-9.-]+|\[[0-9a-f:.]+\]):\d{1,5}(?:[/?#][^\s<>"'`]*)?/gi, scrubBareEndpoint);
}

function sanitizePublicRepoText(value: string): string {
  const original = value;
  let current = value;
  for (let pass = 0; pass < MAX_URL_DECODE_PASSES; pass += 1) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      const sanitized = sanitizePublicRepoTextOnce(current);
      return sanitized !== current
        ? sanitized
        : (/%(?:25|3a|2f|40|5c)/i.test(current) ? '[internal URL omitted]' : original);
    }
    if (decoded === current) {
      const sanitized = sanitizePublicRepoTextOnce(current);
      return sanitized !== current ? sanitized : original;
    }
    current = decoded;
  }
  try {
    return decodeURIComponent(current) !== current ? '[internal URL omitted]' : original;
  } catch {
    return '[internal URL omitted]';
  }
}

function sanitizePublicRepoValue(value: unknown, fieldName?: string): unknown {
  if (typeof value === 'string') {
    if (fieldName?.endsWith('_at') && ISO_TIMESTAMP_PATTERN.test(value)) return value;
    const direct = safePublicUrl(value);
    return direct ?? sanitizePublicRepoText(value);
  }
  if (Array.isArray(value)) return value.map((entry) => sanitizePublicRepoValue(entry, fieldName));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, sanitizePublicRepoValue(entry, key)]),
  );
}

/**
 * Remove Forgejo's server-side URL fields before repository metadata crosses
 * the public NyankoFace boundary. The portal owns the public /git route, so
 * the repository link is deliberately relative and cannot leak an upstream
 * host, port, or SSH endpoint.
 */
export function sanitizePublicRepo(repo: Repo): Repo {
  const raw = repo as Repo & Record<string, unknown>;
  const ownerLogin = repo.owner?.login || repo.full_name.split('/')[0];
  const safeOwner = {
    login: ownerLogin,
    ...(safePublicUrl(repo.owner?.avatar_url)
      ? { avatar_url: safePublicUrl(repo.owner?.avatar_url) }
      : { avatar_url: undefined }),
  };
  const safe = sanitizePublicRepoValue(stripNestedUrlFields(raw)) as Repo & Record<string, unknown>;
  safe.owner = safeOwner;

  for (const field of UPSTREAM_URL_FIELDS) delete safe[field];
  // Forgejo adds many endpoint-specific *_url fields over time. Keep the
  // portal-owned html_url below, but never forward an upstream URL field that
  // was not known when this sanitizer was written.
  for (const field of Object.keys(safe)) {
    if (field.endsWith('_url') && field !== 'html_url' && field !== 'space_url') {
      delete safe[field];
    }
  }
  const safeSpaceUrl = safePublicUrl(repo.space_url);
  if (safeSpaceUrl) safe.space_url = safeSpaceUrl;
  else delete safe.space_url;
  safe.html_url = `/git/${ownerLogin}/${repo.name}`;
  return safe as Repo;
}
