import DocsDirectoryPage from '@/components/DocsDirectoryPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `${ui(locale, 'ナレッジ', 'Knowledge')} - ${appName}`,
    description: ui(locale, 'Gitで管理された記事をタグ、新着順、人気順で閲覧できます。', `Browse Git-backed articles by tag, recency, and popularity on ${appName}.`),
  };
}

export default async function DocsPage({
  searchParams,
}: {
  searchParams?: Promise<{
    newsSort?: string;
    overallSort?: string;
    q?: string;
    sort?: string;
    order?: string;
    tag?: string;
    tagSorts?: string;
  }>;
}) {
  return <DocsDirectoryPage searchParams={await searchParams} />;
}
