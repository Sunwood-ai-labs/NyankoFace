export const SERVICE_ACCOUNT_ID_PATTERN_SOURCE = '[a-zA-Z0-9:_.-]{1,128}';
export const SERVICE_ACCOUNT_ID_PATTERN = new RegExp(`^(?:${SERVICE_ACCOUNT_ID_PATTERN_SOURCE})$`);

export const MIN_TOKEN_TTL_SECONDS = 60;
export const MAX_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60;

export function isValidServiceAccountId(value: unknown): value is string {
  return typeof value === 'string'
    && SERVICE_ACCOUNT_ID_PATTERN.test(value)
    && value !== '.'
    && value !== '..'
    && value === value.trim();
}

export function tokenLifetimeSeconds(
  token: Pick<{ created_at: number; expires_at: number }, 'created_at' | 'expires_at'>,
): number {
  const lifetime = token.expires_at - token.created_at;
  if (!Number.isSafeInteger(lifetime)) return MIN_TOKEN_TTL_SECONDS;
  return Math.min(MAX_TOKEN_TTL_SECONDS, Math.max(MIN_TOKEN_TTL_SECONDS, lifetime));
}

export function isActiveToken(
  token: Pick<{ expires_at: number; revoked_at?: number | null }, 'expires_at' | 'revoked_at'>,
  now = Math.floor(Date.now() / 1000),
): boolean {
  return token.revoked_at == null && Number.isSafeInteger(token.expires_at) && token.expires_at > now;
}
