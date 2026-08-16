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
    if (url.username || url.password) return undefined;
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

function sanitizePublicRepoText(value: string): string {
  return value.replace(/(?:[a-z][a-z0-9+.-]*:[\\/]{1,3}|[\\/]{2})[^\s<>"'`]+/gi, (candidate) => {
    const trailing = candidate.match(/[),.;!?]+$/)?.[0] || '';
    const url = trailing ? candidate.slice(0, -trailing.length) : candidate;
    const safe = safePublicUrl(url);
    return `${safe || '[internal URL omitted]'}${trailing}`;
  });
}

function sanitizePublicRepoValue(value: unknown): unknown {
  if (typeof value === 'string') {
    const direct = safePublicUrl(value);
    return direct ?? sanitizePublicRepoText(value);
  }
  if (Array.isArray(value)) return value.map(sanitizePublicRepoValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, sanitizePublicRepoValue(entry)]),
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
