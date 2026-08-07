import { headers } from 'next/headers';
import { notFound, redirect } from 'next/navigation';
import McpAdminConsole from '@/components/McpAdminConsole';
import HfIcon from '@/components/HfIcon';
import { forgejoBrowserSession } from '@/lib/forgejo-session';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';
import { isSecureAdminTransport } from '@/lib/mcp-admin-contract';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  return { title: `${ui(locale, 'MCP管理', 'MCP administration')} - ${getAppName()}` };
}

export default async function McpAdminPage() {
  const locale = await getLocale();
  const requestHeaders = await headers();
  if (!isSecureAdminTransport(requestHeaders)) notFound();
  const cookie = requestHeaders.get('cookie') || '';
  const session = await forgejoBrowserSession(cookie);
  if (!session.authenticated) redirect('/git/user/login?redirect_to=/admin/mcp');
  if (!session.isAdmin) notFound();

  return (
    <main className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:py-10" data-mcp-admin-page>
      <header className="mb-7 border-b border-zinc-200 pb-6 dark:border-zinc-800">
        <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-violet-600 dark:text-violet-300">
          <HfIcon name="mcp" className="h-4 w-4" /> MCP control plane
        </p>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-zinc-950 dark:text-white sm:text-4xl">
          {ui(locale, 'MCP接続とアクセス管理', 'MCP connections and access')}
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-zinc-600 dark:text-zinc-300 sm:text-base">
          {ui(locale,
            'サービスアカウント、最小権限Token、policy、接続確認、監査証跡を一か所で管理します。秘密値は発行直後の一度だけ表示されます。',
            'Manage service accounts, least-privilege tokens, policy, connection checks, and audit evidence. Secrets are shown once immediately after issue.',
          )}
        </p>
      </header>
      <McpAdminConsole locale={locale} />
    </main>
  );
}
