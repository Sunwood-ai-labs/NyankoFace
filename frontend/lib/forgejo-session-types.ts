export interface ForgejoBrowserSession {
  authenticated: boolean;
  username?: string;
  displayName?: string;
  avatarUrl?: string;
  isAdmin?: boolean;
}

export function hasRenderedForgejoAdminControl(html: string): boolean {
  // Forgejo's custom header can include dormant navigation markup in scripts.
  // Only rendered anchors may grant the local admin navigation audience.
  const renderedHtml = html
    .replace(/<!--[^]*?-->/g, '')
    .replace(/<(script|style|template)\b[^>]*>[^]*?<\/\1\s*>/gi, '')
    .replace(/<(script|style|template)\b[^>]*>[^]*$/gi, '');
  return /<a\b[^>]*\shref\s*=\s*["'](?:\/git)?\/admin(?:[/?#][^"']*)?["'][^>]*>/i.test(renderedHtml);
}
