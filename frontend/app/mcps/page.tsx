import ListingPage from '@/components/ListingPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `MCPs - ${appName}`,
    description: ui(locale, `${appName}で公開されているModel Context Protocolサーバーを探せます。`, `Browse Model Context Protocol servers hosted on ${appName}.`),
  };
}

export default async function McpsPage({ searchParams }: { searchParams?: Promise<{ q?: string; sort?: string }> }) {
  const resolvedSearchParams = await searchParams;
  const locale = await getLocale();
  return (
    <ListingPage
      topic="mcp"
      title="MCPs"
      icon="mcp"
      placeholder={ui(locale, 'MCPサーバーを検索', 'Search MCP servers')}
      searchParams={resolvedSearchParams}
    />
  );
}
