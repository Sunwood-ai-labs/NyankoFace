import SpacesDirectoryPage from '@/components/SpacesDirectoryPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `Spaces - ${appName}`,
    description: ui(locale, `${appName}で共有されている実行可能なAIアプリを探せます。`, `Explore runnable AI applications shared on ${appName}.`),
  };
}

export default async function SpacesPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; sort?: string; order?: string; page?: string }>;
}) {
  const resolvedSearchParams = await searchParams;
  return (
    <SpacesDirectoryPage searchParams={resolvedSearchParams} />
  );
}
