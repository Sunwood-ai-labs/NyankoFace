import CharactersDirectoryPage from '@/components/CharactersDirectoryPage';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  const appName = getAppName();
  return {
    title: `${ui(locale, 'キャラクター', 'Characters')} - ${appName}`,
    description: ui(locale, 'PuruPuru PNGtuber、Codex Pet、キャラクターシートを探せます。', 'Browse PuruPuru PNGtubers, Codex Pets, and character sheets.'),
  };
}

export default async function CharactersPage({
  searchParams,
}: {
  searchParams?: Promise<{ q?: string; sort?: string; order?: string }>;
}) {
  return <CharactersDirectoryPage searchParams={await searchParams} />;
}
