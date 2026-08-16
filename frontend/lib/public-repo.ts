import type { Repo } from './forgejo';

const UPSTREAM_URL_FIELDS = [
  'url',
  'clone_url',
  'ssh_url',
  'mirror_url',
  'original_url',
  'website',
] as const;

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
  if (configuredForgejoHostname() === host) return true;
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
    (!host.includes('.') && !host.includes(':'))
  ) return true;
  const octets = host.split('.').map((part) => Number(part));
  if (octets.length === 4 && octets.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)) {
    const [first, second, third, fourth] = octets;
    if (
      first === 0 ||
      first === 10 ||
      first === 127 ||
      (first === 100 && second >= 64 && second <= 127) ||
      (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168) ||
      (first === 192 && second === 0 && third === 0 && fourth !== 9 && fourth !== 10) ||
      (first === 192 && second === 0 && third === 2) ||
      (first === 192 && second === 88 && third === 99) ||
      (first === 198 && second >= 18 && second <= 19) ||
      (first === 198 && second === 51 && third === 100) ||
      (first === 203 && second === 0 && third === 113) ||
      (first >= 224)
    ) return true;
  }
  if (host === '0.0.0.0' || host === '::1' || host === '::') return true;
  if (/^f[cd][0-9a-f:]*$/i.test(host) || /^fe[89ab][0-9a-f:]*$/i.test(host)) return true;
  const mappedHex = host.match(/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/i);
  if (mappedHex) {
    const high = Number.parseInt(mappedHex[1], 16);
    const low = Number.parseInt(mappedHex[2], 16);
    return isPrivateHostname(`${high >> 8}.${high & 255}.${low >> 8}.${low & 255}`);
  }
  return /^::ffff:(?:10\.|127\.|169\.254\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/i.test(host);
}

export function safePublicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (trimmed.includes('\\') || /[\u0000-\u001f\u007f]/.test(trimmed)) return undefined;
  // A protocol-relative URL such as //forgejo:3000/... is not a safe
  // root-relative path; browsers resolve it against the current scheme.
  if (trimmed.startsWith('/') && !trimmed.startsWith('//')) return trimmed;
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
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
  const safe = stripNestedUrlFields(raw) as Repo & Record<string, unknown>;
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
