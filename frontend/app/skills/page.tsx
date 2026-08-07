import ListingPage from '@/components/ListingPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `${ui(locale, 'スキル', 'Skills')} - ${appName}`,
    description: ui(locale, `${appName}で公開されている再利用可能なエージェントスキルを探せます。`, `Browse reusable agent skills hosted on ${appName}.`),
  };
}

export default async function SkillsPage({ searchParams }: { searchParams?: Promise<{ q?: string; sort?: string }> }) {
  const resolvedSearchParams = await searchParams;
  const locale = await getLocale();
  return (
    <ListingPage
      topic="skill"
      title={ui(locale, 'スキル', 'Skills')}
      icon="skill"
      placeholder={ui(locale, 'スキルを検索', 'Search skills')}
      searchParams={resolvedSearchParams}
    />
  );
}
