import 'server-only';
import { hasRenderedForgejoAdminControl, type ForgejoBrowserSession } from './forgejo-session-types';
import {
  boundedForgejoFetch,
  boundedForgejoFetchAndRead,
  FORGEJO_FETCH_TIMEOUT_MS,
} from './mcp-admin-contract';

const FORGEJO_WEB = (process.env.FORGEJO_WEB || 'http://forgejo:3000').replace(/\/$/, '');

export class ForgejoUnavailable extends Error {
  constructor() { super('forgejo_unavailable'); }
}

type ForgejoBrowserSessionOptions = { failClosed?: boolean };

function decodeHtml(value: string): string {
  return value
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function attribute(tag: string, name: string): string | undefined {
  const match = tag.match(new RegExp(`${name}="([^"]*)"`, 'i'));
  return match ? decodeHtml(match[1]) : undefined;
}

function publicForgejoPath(path: string | undefined): string | undefined {
  if (!path?.startsWith('/')) return undefined;
  return path === '/git' || path.startsWith('/git/') ? path : `/git${path}`;
}

function seededProfileAvatar(username: string): string | undefined {
  const avatarAliases: Record<string, string> = {
    'nyankoface-admin': 'lina-park',
  };
  const alias = avatarAliases[username.toLowerCase()];
  return alias
    ? `/git/assets/img/avatars/${alias}.png?v=20260718-seraphim-characters3`
    : undefined;
}

export function parseForgejoBrowserSession(html: string): ForgejoBrowserSession {
  const signedInMatch = html.match(/Signed in as\s*<strong>([^<]+)<\/strong>/i);
  const profileAvatarTags = html.match(/<img[^>]*class="[^"]*\bavatar\b[^"]*"[^>]*>/gi) || [];
  const profileAvatarTag = profileAvatarTags.find((tag) => {
    const title = attribute(tag, 'title');
    const src = attribute(tag, 'src');
    return Boolean(title && src && !tag.includes('${'));
  });
  const username = signedInMatch?.[1]?.trim() || (profileAvatarTag ? attribute(profileAvatarTag, 'title')?.trim() : undefined);
  if (!username) return { authenticated: false };

  const decodedUsername = decodeHtml(username);
  const rawAvatarUrl = profileAvatarTag ? attribute(profileAvatarTag, 'src') : undefined;
  const avatarUrl = seededProfileAvatar(decodedUsername) || publicForgejoPath(rawAvatarUrl);
  const displayName = (profileAvatarTag ? attribute(profileAvatarTag, 'title') : undefined) || decodedUsername;
  const isAdmin = hasRenderedForgejoAdminControl(html);
  return {
    authenticated: true,
    username: decodedUsername,
    displayName,
    isAdmin,
    ...(avatarUrl ? { avatarUrl } : {}),
  };
}

export async function forgejoBrowserSession(
  cookie: string,
  timeoutMs = FORGEJO_FETCH_TIMEOUT_MS,
  options: ForgejoBrowserSessionOptions = {},
): Promise<ForgejoBrowserSession> {
  if (!cookie) return { authenticated: false };
  try {
    const result = await boundedForgejoFetchAndRead(fetch, `${FORGEJO_WEB}/user/settings`, {
      headers: { Cookie: cookie, Accept: 'text/html' },
      cache: 'no-store',
      redirect: 'manual',
    }, (response) => response.ok ? response.text() : Promise.resolve(''), timeoutMs);
    if (!result) {
      if (options.failClosed) throw new ForgejoUnavailable();
      return { authenticated: false };
    }
    const { response, value: html } = result;
    if (!response.ok) return { authenticated: false };
    return parseForgejoBrowserSession(html);
  } catch (error) {
    if (error instanceof ForgejoUnavailable) throw error;
    return { authenticated: false };
  }
}

export async function verifyForgejoPassword(
  username: string,
  password: string,
  otp: string,
  timeoutMs = FORGEJO_FETCH_TIMEOUT_MS,
): Promise<boolean> {
  if (!username || !password || password.length > 1024) return false;
  try {
    const result = await boundedForgejoFetchAndRead(fetch, `${FORGEJO_WEB}/api/v1/user`, {
      headers: {
        Authorization: `Basic ${Buffer.from(`${username}:${password}`, 'utf8').toString('base64')}`,
        Accept: 'application/json',
        ...(otp ? { 'X-Forgejo-OTP': otp } : {}),
      },
      cache: 'no-store',
      redirect: 'manual',
    }, (response) => response.ok ? response.json() as Promise<{ login?: unknown; is_admin?: unknown }> : Promise.resolve(null), timeoutMs);
    if (!result) throw new ForgejoUnavailable();
    const { response, value: user } = result;
    if (!response.ok) return false;
    return user?.login === username && user?.is_admin === true;
  } catch (error) {
    if (error instanceof ForgejoUnavailable) throw error;
    return false;
  }
}

export async function forgejoLogout(cookie: string): Promise<Response | null> {
  if (!cookie) return null;
  try {
    return await boundedForgejoFetch(fetch, `${FORGEJO_WEB}/user/logout`, {
      method: 'POST',
      headers: { Cookie: cookie },
      cache: 'no-store',
      redirect: 'manual',
    });
  } catch {
    return null;
  }
}

