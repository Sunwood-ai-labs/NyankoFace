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
  /(?<=[?&#=\s([{<])(?=((?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'&]+\.git(?:[/?#][^\s<>"'&]*)?))/gi,
  /(?<![a-z0-9+.-])(?=([a-z][a-z0-9+.-]*:[\\/]{1,3}[^\s<>"'`&]+))/gi,
  /(?<![a-z0-9+.-])(?=(https?:(?![\\/])[^\s<>"'`&]+))/gi,
  /(?<=[?&#=\s([{<])(?=([a-z][a-z0-9+.-]*:[^\s<>"'`&]+))/gi,
  /(?<!:)(?=(\/[\/][^\s<>"'`&]+))/gi,
  /(?=(\b[^\s<>"'`&]+@(?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'`&]+))/gi,
  /(?<=[?&#=\s([{<])(?=((?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'&]+\/[^\s<>"'`]+))/gi,
  /(?<=[?&#=\s([{<])(?=((?:\[[^\]\s<>"'`]+\]):[^\s<>"'`]+))/gi,
];
const EXTERNAL_TARGET_PARAMETER_PATTERN = /(?:^|[?&#])((?:next|url|uri|redirect|redirect_url|redirect_uri|return|return_to|return_url|target|destination|dest|link|href|clone|repository|repo|callback|continue))\s*=\s*$/i;
const GIT_REMOTE_TARGET_PARAMETERS = new Set(['clone', 'repository', 'repo']);
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
    return normalizedHostnameForClassification(new URL(configured).hostname);
  } catch {
    return undefined;
  }
}

function normalizedHostnameForClassification(hostname: string): string {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  const scopeSeparator = host.indexOf('%');
  if (scopeSeparator >= 0) return normalizedHostnameForClassification(host.slice(0, scopeSeparator));
  if (!host.includes(':')) {
    try {
      return new URL('http://' + host + '/').hostname
        .toLowerCase()
        .replace(/^\[|\]$/g, '')
        .replace(/\.+$/, '');
    } catch {
      return host;
    }
  }
  try {
    return new URL(`http://[${host}]/`).hostname
      .toLowerCase()
      .replace(/^\[|\]$/g, '')
      .replace(/\.+$/, '');
  } catch {
    return host;
  }
}

function isPrivateHostname(hostname: string): boolean {
  const host = normalizedHostnameForClassification(hostname);
  return configuredForgejoHostname() === host || isNonPublicHostname(host);
}

function canonicalNumericIpv4Host(hostname: string, port?: string, allowShortDecimal = false): string | undefined {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
  const isDottedNumeric = /^[0-9a-fx]+(?:\.[0-9a-fx]+){1,3}$/i.test(host);
  const isHexNumeric = /^0x[0-9a-f]+$/i.test(host);
  const isLongDecimal = /^\d{4,}$/.test(host);
  const isShortDecimalEndpoint = /^\d{1,3}$/.test(host) && (allowShortDecimal || port !== undefined || host.length === 3);
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

function isEstablishedPrivateEndpointHost(hostname: string, port?: string, allowShortDecimal = false): boolean {
  const host = normalizedHostnameForClassification(hostname);
  if (configuredForgejoHostname() === host || PRIVATE_BARE_HOSTS.has(host)) return true;
  const canonicalNumericHost = canonicalNumericIpv4Host(host, port, allowShortDecimal);
  if (canonicalNumericHost && isPrivateHostname(canonicalNumericHost)) return true;
  return (host.includes('.') || host.includes(':')) && isPrivateHostname(host);
}

function parseScpTarget(value: string): { host: string; hasUser: boolean } | undefined {
  const match = value.match(/^(?:([^\s<>"'`&]+)@)?(\[[^\]\s<>"'`&]+\]|[^\s<>"'`&@:/?]+):[^\s<>"'`&]+$/i);
  if (!match) return undefined;
  const host = match[2];
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) && !host.startsWith('[') && !host.includes('.')) return undefined;
  return { host, hasUser: Boolean(match[1]) };
}

function isUnsafeScpHost(target: { host: string; hasUser: boolean }): boolean {
  if (target.hasUser) {
    const canonicalNumericHost = canonicalNumericIpv4Host(target.host, undefined, true);
    return canonicalNumericHost
      ? isPrivateHostname(canonicalNumericHost)
      : isPrivateHostname(target.host);
  }
  return isEstablishedPrivateEndpointHost(target.host, undefined, true);
}

function externalTargetParameter(source: string, candidateStart: number): string | undefined {
  return source.slice(0, candidateStart).match(EXTERNAL_TARGET_PARAMETER_PATTERN)?.[1].toLowerCase();
}

function decodePercentEscapesBestEffort(value: string): string {
  let result = '';
  let index = 0;
  while (index < value.length) {
    if (value[index] !== '%') {
      result += value[index];
      index += 1;
      continue;
    }
    const runStart = index;
    while (index + 2 < value.length && value[index] === '%' && /^[0-9a-f]{2}$/i.test(value.slice(index + 1, index + 3))) {
      index += 3;
    }
    if (index === runStart) {
      result += value[index];
      index += 1;
      continue;
    }
    const run = value.slice(runStart, index);
    let runOffset = 0;
    while (runOffset < run.length) {
      let decoded = '';
      let decodedEnd = run.length;
      while (decodedEnd > runOffset) {
        try {
          decoded = decodeURIComponent(run.slice(runOffset, decodedEnd));
          break;
        } catch {
          decodedEnd -= 3;
        }
      }
      if (decodedEnd === runOffset) {
        result += run.slice(runOffset, runOffset + 3);
        runOffset += 3;
      } else {
        result += decoded;
        runOffset = decodedEnd;
      }
    }
  }
  return result;
}

function containsUnsafeNestedUrl(value: string): boolean {
  let current = value;
  for (let pass = 0; pass <= MAX_URL_DECODE_PASSES; pass += 1) {
    // Percent decoding can reveal controls that were not present in the
    // original public-looking URL. Reject them before WHATWG URL parsing can
    // normalize them away.
    if (current.includes('\\') || /[\u0000-\u001f\u007f]/.test(current)) return true;
    if (/(?:^|[?&#=\s([{<])https?:[\\/]{1,3}[^/&#?]*@/i.test(current)) return true;
    for (const pattern of NESTED_URL_PATTERNS) {
      for (const match of current.matchAll(pattern)) {
        const candidate = (match[1] || '').replace(/[),.;!?]+$/, '');
        const targetParameter = externalTargetParameter(current, match.index ?? 0);
        const isSlashlessNonHttpScheme = /^[a-z][a-z0-9+.-]*:(?![\\/])/i.test(candidate)
          && !/^https?:/i.test(candidate);
        if (isSlashlessNonHttpScheme && !targetParameter) continue;
        if (
          isSlashlessNonHttpScheme
          && targetParameter
          && !GIT_REMOTE_TARGET_PARAMETERS.has(targetParameter)
        ) return true;
        if (
          candidate.startsWith('//') &&
          !targetParameter
        ) continue;
        if (
          candidate.startsWith('//') &&
          match.index > 0 &&
          !/[?&#=\s([{<]/.test(current[match.index - 1])
        ) continue;
        const scpTarget = parseScpTarget(candidate);
        if (scpTarget) {
          // A suffix such as `@types:node` in an ordinary query is not a Git
          // remote. Only classify SCP syntax when it is carried by an
          // explicitly recognized target parameter; retained text is scrubbed
          // separately by sanitizePublicRepoTextOnce.
          if (!targetParameter) continue;
          if (isUnsafeScpHost(scpTarget)) return true;
          continue;
        }
        try {
          const nested = candidate.startsWith('//')
            ? new URL(candidate, 'http://nyankoface.invalid')
            : new URL(candidate);
          const slashlessHttpTarget = /^https?:[^\\/]/i.test(candidate);
          const unsafeHost = slashlessHttpTarget
            ? targetParameter
              ? isPrivateHostname(nested.hostname)
              : isEstablishedPrivateEndpointHost(nested.hostname)
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
    const decoded = decodePercentEscapesBestEffort(current);
    if (decoded === current) break;
    current = decoded;
  }
  // A value that still changes after the bounded decode budget is ambiguous;
  // do not preserve it at a public metadata boundary.
  return decodePercentEscapesBestEffort(current) !== current;
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
    const nestedPath = url.pathname.replace(/^\/+/, '/');
    if (containsUnsafeNestedUrl(`${nestedPath}${url.search}${url.hash}`)) return undefined;
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
    const scpTarget = parseScpTarget(url);
    if (scpTarget) {
      return isUnsafeScpHost(scpTarget)
        ? '[internal URL omitted]' + trailing
        : candidate;
    }
    const safe = safePublicUrl(url);
    return `${safe || '[internal URL omitted]'}${trailing}`;
  };
  const scrubSlashlessHttpTarget = (candidate: string): string => {
    const trailing = candidate.match(/[),.;!]+$/)?.[0] || '';
    const url = trailing ? candidate.slice(0, -trailing.length) : candidate;
    try {
      const parsed = new URL(url);
      const slashlessHttpTarget = /^https?:[^\\/]/i.test(url);
      const singleLabelPort = slashlessHttpTarget
        && Boolean(parsed.port)
        && !parsed.hostname.includes('.')
        && !parsed.hostname.includes(':');
      return parsed.username || parsed.password || singleLabelPort || isEstablishedPrivateEndpointHost(parsed.hostname, parsed.port || undefined)
        ? `[internal URL omitted]${trailing}`
        : candidate;
    } catch {
      return `[internal URL omitted]${trailing}`;
    }
  };
  const scrubBareEndpoint = (candidate: string): string => {
    const endpoint = candidate.match(/^((?:[a-z0-9_.-]+|\[[^\]\s<>"'`]+\])):(\d{1,5})(?:[/?#][^\s<>"'`]*)?$/i);
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
    const isGitRepositoryTarget = /\.git(?:[/?#]|[),.;!?]|$)/i.test(candidate);
    return (isGitRepositoryTarget ? isPrivateHostname(host) : isEstablishedPrivateEndpointHost(host, undefined, true))
      ? '[internal URL omitted]'
      : candidate;
  };
  const scrubBareHostPath = (candidate: string): string => {
    const trailing = candidate.match(/[),.;!?]+$/)?.[0] || '';
    const hostPath = trailing ? candidate.slice(0, -trailing.length) : candidate;
    const match = hostPath.match(/^([a-z0-9][a-z0-9_.-]*|\[[^\]\s<>'"`&]+\])\/[^\s<>'"`&]+$/i);
    if (!match) return candidate;
    const host = normalizedHostnameForClassification(match[1]);
    if (!match[1].includes('.') && !match[1].startsWith('[') && configuredForgejoHostname() !== host) return candidate;
    return isPrivateHostname(match[1])
      ? `[internal URL omitted]${trailing}`
      : candidate;
  };
  return value
    .replace(/(?!(?:[a-z]:[\\/]))(?:[a-z][a-z0-9+.-]*:[\\/]{1,3}|[\\/]{2})[^\s<>"'`]+/gi, scrub)
    .replace(/(?<![a-z0-9+.-])(https?:(?![\\/])[^\s<>"'`]+)/gi, scrubSlashlessHttpTarget)
    .replace(/\b[^\s<>"'`&]+@(?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'`]+/gi, scrub)
    .replace(/(?<![a-z0-9_.-])(?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'`]*\/[^\s<>"'`]+/gi, scrubUsernameLessScpEndpoint)
    .replace(/(?<![a-z0-9_.-])(?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):[^\s<>"'`]+\.git(?:[/?#][^\s<>"'`]*)?/gi, scrubUsernameLessScpEndpoint)
    .replace(/(?<![a-z0-9_.-])(\[[^\]\s<>"'`]+\]):[^\s<>"'`]+/gi, scrubUsernameLessScpEndpoint)
    .replace(/(?<![a-z0-9_.-])(?:[^\s<>"'`&@:/?]+|\[[^\]\s<>"'`&]+\]):\d{1,5}(?:[/?#][^\s<>"'`]*)?/gi, scrubBareEndpoint)
    .replace(/(?<![a-z0-9_.-])(?:[a-z0-9][a-z0-9_.-]*|\[[^\]\s<>"'`&]+\])\/[^\s<>"'`&]+/gi, scrubBareHostPath);
}

function decodeSafePercentSequences(value: string): string {
  return value.replace(/(?:%[0-9a-f]{2})+/gi, (encoded) => {
    try {
      return decodeURIComponent(encoded);
    } catch {
      return encoded;
    }
  });
}

function sanitizePublicRepoText(value: string): string {
  const original = value;
  let current = value;
  let unsafeChanged = false;
  for (let pass = 0; pass < MAX_URL_DECODE_PASSES; pass += 1) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      const safelyDecoded = decodeSafePercentSequences(current);
      const sanitized = sanitizePublicRepoTextOnce(safelyDecoded);
      if (sanitized !== safelyDecoded) {
        current = sanitized;
        unsafeChanged = unsafeChanged || sanitized.includes('[internal URL omitted]');
        continue;
      }
      if (safelyDecoded !== current) {
        current = safelyDecoded;
        continue;
      }
      return unsafeChanged ? current : original;
    }
    if (decoded === current) {
      const sanitized = sanitizePublicRepoTextOnce(current);
      return sanitized.includes('[internal URL omitted]') ? sanitized : original;
    }
    current = decoded;
  }
  const sanitized = sanitizePublicRepoTextOnce(current);
  if (sanitized !== current) {
    // Keep safe text exactly as supplied after the final bounded decode pass.
    // sanitizePublicTextOnce may otherwise normalize a public URL by adding a
    // trailing slash, making an eight-times-encoded safe value look changed.
    return sanitized.includes('[internal URL omitted]') ? sanitized : original;
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
  const operationalDefaultBranch = typeof raw.__nyankofaceOperationalDefaultBranch === 'string'
    ? raw.__nyankofaceOperationalDefaultBranch.trim()
    : typeof repo.default_branch === 'string'
      ? repo.default_branch.trim()
      : '';
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
  if (operationalDefaultBranch) {
    Object.defineProperty(safe, '__nyankofaceOperationalDefaultBranch', {
      configurable: true,
      enumerable: false,
      value: operationalDefaultBranch,
      writable: false,
    });
  }
  return safe as Repo;
}
