import ListingPage from '@/components/ListingPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `${ui(locale, 'モデル', 'Models')} - ${appName}`,
    description: ui(locale, `${appName}で共有されている機械学習モデルを探せます。`, `Explore machine learning models shared on ${appName}.`),
  };
}

export default async function ModelsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string }>;
}) {
  const resolvedSearchParams = await searchParams;
  const locale = await getLocale();
  return (
    <ListingPage
      topic="model"
      title={ui(locale, 'モデル', 'Models')}
      icon="model"
      placeholder={ui(locale, '名前で絞り込む', 'Filter by name')}
      searchParams={resolvedSearchParams}
    />
  );
}
