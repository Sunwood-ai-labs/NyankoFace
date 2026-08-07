import ListingPage from '@/components/ListingPage';
import { getAppName } from '@/lib/app-config';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  return {
    title: `Automations - ${getAppName()}`,
    description: ui(
      locale,
      '安全性と互換性を確認してから再利用できる、版管理されたCodex Automation。',
      'Versioned Codex Automations with reviewable safety and compatibility preflight.',
    ),
  };
}

export default async function AutomationsPage({
  searchParams,
}: {
  searchParams?: Promise<{ q?: string; sort?: string }>;
}) {
  const locale = await getLocale();
  return (
    <ListingPage
      topic="automation"
      title="Automations"
      icon="automation"
      placeholder={ui(locale, 'Automationを検索', 'Search Automations')}
      searchParams={await searchParams}
    />
  );
}
