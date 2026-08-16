import type { Repo } from './forgejo';

const UPSTREAM_URL_FIELDS = [
  'url',
  'clone_url',
  'ssh_url',
  'mirror_url',
  'original_url',
] as const;

function isPrivateHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host.endsWith('.local') ||
    host.endsWith('.internal') ||
    host === 'forgejo' ||
    host === 'frontend' ||
    host === 'gateway' ||
    host === 'nyankoface-mcp' ||
    host === 'spaces-runner'
  ) return true;
  if (/^10\.(?:\d{1,3}\.){2}\d{1,3}$/.test(host)) return true;
  if (/^192\.168\.(?:\d{1,3}\.)\d{1,3}$/.test(host)) return true;
  const private172 = host.match(/^172\.(\d{1,3})\.(?:\d{1,3}\.)\d{1,3}$/);
  if (private172 && Number(private172[1]) >= 16 && Number(private172[1]) <= 31) return true;
  return host === '127.0.0.1' || host === '::1' || host === '0.0.0.0';
}

function safePublicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (trimmed.startsWith('/')) return trimmed;
  try {
    const url = new URL(trimmed);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    return isPrivateHostname(url.hostname) ? undefined : url.href;
  } catch {
    return undefined;
  }
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
    ...repo.owner,
    ...(safePublicUrl(repo.owner?.avatar_url)
      ? { avatar_url: safePublicUrl(repo.owner?.avatar_url) }
      : { avatar_url: undefined }),
  };
  const safe = { ...raw, owner: safeOwner } as Repo & Record<string, unknown>;

  for (const field of UPSTREAM_URL_FIELDS) delete safe[field];
  safe.html_url = `/git/${ownerLogin}/${repo.name}`;
  return safe as Repo;
}
