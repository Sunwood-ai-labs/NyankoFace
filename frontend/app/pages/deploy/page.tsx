import PagesDeployWizard from '@/components/PagesDeployWizard';
import HfIcon from '@/components/HfIcon';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  return {
    title: `${ui(locale, 'Pagesを公開', 'Deploy Pages')} - ${getAppName()}`,
  };
}

export default async function PagesDeployPage({
  searchParams,
}: {
  searchParams?: Promise<{ owner?: string; repo?: string }>;
}) {
  const locale = await getLocale();
  const params = await searchParams;

  return (
    <main className="mx-auto w-full max-w-[1180px] px-4 py-8 sm:py-10" data-pages-deploy-page>
      <header className="mb-7 border-b border-zinc-200 pb-6 dark:border-zinc-800">
        <p className="nyankoface-pages-kicker flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">
          <HfIcon name="pages" className="h-3.5 w-3.5" />
          NyankoFace Pages
        </p>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-zinc-950 dark:text-white sm:text-4xl">
          {locale === 'ja' ? (
            <>
              <span className="whitespace-nowrap">静的サイトをGitから</span>
              <br className="sm:hidden" />
              <span className="whitespace-nowrap">公開する</span>
            </>
          ) : 'Publish a static site from Git'}
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-zinc-600 dark:text-zinc-300 sm:text-base">
          {ui(
            locale,
            'Spacesを起動せず、public ForgejoリポジトリだけでHTMLやVitePressを公開します。方式を選び、書き込むファイルを確認してからデプロイしてください。',
            'Publish HTML or VitePress directly from a public Forgejo repository without starting a Space. Choose a method and review every repository write before deploying.',
          )}
        </p>
      </header>
      <PagesDeployWizard
        initialOwner={params?.owner?.trim() || ''}
        initialRepo={params?.repo?.trim() || ''}
      />
    </main>
  );
}
