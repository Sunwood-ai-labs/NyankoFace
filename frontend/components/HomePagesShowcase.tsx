import Link from 'next/link';
import type { HomePagesPreview } from '@/lib/pages-discovery';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import type { Locale } from '@/lib/i18n';
import { ui } from '@/lib/i18n';
import HfIcon from './HfIcon';

export default function HomePagesShowcase({
  preview,
  locale,
}: {
  preview: HomePagesPreview;
  locale: Locale;
}) {
  return (
    <section
      className="nyankoface-home-pages mx-auto mb-12 max-w-[1180px] scroll-mt-20 overflow-hidden rounded-[1.75rem] border border-indigo-200 bg-indigo-50/50 shadow-sm dark:border-indigo-900 dark:bg-indigo-950/20"
      aria-labelledby="home-pages-title"
      data-home-pages-state={preview.state}
    >
      <div className="grid gap-8 px-5 py-7 sm:px-8 lg:grid-cols-[0.7fr_1.3fr] lg:items-start lg:px-10 lg:py-10">
        <div className="min-w-0">
          <p className="nyankoface-home-pages-kicker flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-[0.2em] text-indigo-700 dark:text-indigo-300">
            <HfIcon name="pages" className="h-3.5 w-3.5" />
            NyankoFace Pages
          </p>
          <h2 id="home-pages-title" className="mt-3 text-3xl font-extrabold leading-tight text-zinc-950 dark:text-white sm:text-4xl">
            {ui(locale, '公開されたサイトを見つける。', 'Discover published sites.')}
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-7 text-zinc-600 dark:text-zinc-300">
            {ui(
              locale,
              'Pagesは、ドキュメントやポートフォリオなどの静的サイトをそのまま公開する場所です。Spacesは、GradioやDockerなど実行中のAIアプリを試す場所です。',
              'Pages publishes static sites such as documentation and portfolios. Spaces is for trying live AI apps powered by Gradio, Docker, and other runtimes.',
            )}
          </p>
          <nav aria-label={ui(locale, 'Pagesの閲覧と公開', 'Browse and publish Pages')} className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/pages"
              className="nyankoface-home-pages-browse inline-flex h-11 items-center justify-center gap-2 rounded-full bg-indigo-700 px-5 text-sm font-bold text-white shadow-sm transition hover:bg-indigo-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
            >
              <HfIcon name="globe" className="h-3.5 w-3.5" />
              {ui(locale, 'Pagesを見る', 'Browse Pages')}
            </Link>
            <Link
              href="/pages/deploy"
              className="nyankoface-home-pages-publish inline-flex h-11 items-center justify-center gap-2 rounded-full border border-indigo-300 bg-white px-5 text-sm font-bold text-indigo-800 shadow-sm transition hover:border-indigo-400 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:border-indigo-700 dark:bg-zinc-950 dark:text-indigo-200 dark:hover:bg-indigo-950/60"
            >
              <HfIcon name="plus" className="h-3.5 w-3.5" />
              {ui(locale, 'Pagesを公開する', 'Publish a Page')}
            </Link>
          </nav>
        </div>

        <div className="min-w-0">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-sm font-extrabold text-zinc-950 dark:text-white">
              {ui(locale, '最新の公開Pages', 'Latest published Pages')}
            </h3>
            <Link
              href="/pages"
              aria-label={ui(locale, '公開済みPagesをすべて見る', 'Browse all published Pages')}
              className="inline-flex shrink-0 items-center gap-1 text-xs font-bold text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300"
            >
              {ui(locale, 'すべて見る', 'Browse all')}
              <HfIcon name="arrowRight" className="h-3 w-3" />
            </Link>
          </div>

          {preview.pages.length > 0 ? (
            <div className="grid gap-3" data-home-pages-list>
              {preview.pages.map(({ repo, owner, publicUrl, source, metrics }) => (
                <article key={repo.full_name} className="nyankoface-home-page-card rounded-2xl border border-indigo-100 bg-white p-4 shadow-sm dark:border-indigo-900 dark:bg-zinc-900">
                  <div className="flex items-start gap-3">
                    <span className="nyankoface-home-page-icon flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                      <HfIcon name="globe" className="h-4 w-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <a
                        href={publicUrl}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={ui(locale, `${repo.full_name}の公開サイトを見る`, `Visit the published site for ${repo.full_name}`)}
                        className="block truncate font-mono text-sm font-bold text-zinc-950 hover:text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-white dark:hover:text-indigo-300"
                      >
                        {repo.name}
                        <HfIcon name="external" className="ml-1.5 inline h-2.5 w-2.5" />
                      </a>
                      <p className="mt-1 truncate text-xs text-zinc-500 dark:text-zinc-400">{owner} · {source}</p>
                    </div>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
                    {repo.description || ui(locale, '公開中のNyankoFace Pagesサイト', 'A published NyankoFace Pages site')}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-zinc-100 pt-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <span>{locale === 'ja' ? timeAgoJa(repo.updated_at) : timeAgoEn(repo.updated_at)}</span>
                    <span
                      className="inline-flex items-center gap-1"
                      aria-label={metrics.availability === 'available'
                        ? ui(locale, `いいね数 ${metrics.likes}`, `Likes ${metrics.likes}`)
                        : ui(locale, 'いいね数 取得不可', 'Likes unavailable')}
                    >
                      <HfIcon name="heart" className="h-3 w-3" />
                      {metrics.availability === 'available' ? metrics.likes : '—'}
                    </span>
                    <span
                      className="inline-flex items-center gap-1"
                      aria-label={metrics.availability === 'available'
                        ? ui(locale, `閲覧数 ${metrics.views}`, `Views ${metrics.views}`)
                        : ui(locale, '閲覧数 取得不可', 'Views unavailable')}
                    >
                      <HfIcon name="eye" className="h-3 w-3" />
                      {metrics.availability === 'available' ? metrics.views : '—'}
                    </span>
                    <a
                      href={publicUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto font-bold text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300"
                    >
                      {ui(locale, 'サイトを見る', 'Visit site')}
                    </a>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="nyankoface-home-pages-fallback rounded-2xl border border-dashed border-indigo-200 bg-white/80 p-6 text-center dark:border-indigo-900 dark:bg-zinc-900/80" role="status">
              <HfIcon name={preview.state === 'unavailable' ? 'clock' : 'pages'} className="mx-auto h-6 w-6 text-indigo-500 dark:text-indigo-300" />
              <p className="mt-3 text-sm font-bold text-zinc-950 dark:text-white">
                {preview.state === 'unavailable'
                  ? ui(locale, '公開サイトを一時的に取得できません', 'Published sites are temporarily unavailable')
                  : ui(locale, '最初のPagesを公開してみませんか？', 'Publish the first Page')}
              </p>
              <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-zinc-500 dark:text-zinc-400">
                {preview.state === 'unavailable'
                  ? ui(locale, '一覧は引き続き開けます。時間をおいて再読み込みするか、公開手順を確認してください。', 'You can still open the directory. Reload later or review the publishing flow.')
                  : ui(locale, '公開済みPagesがここに表示されます。静的HTMLやVitePressから始められます。', 'Published Pages will appear here. Start with static HTML or VitePress.')}
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-3 text-xs font-bold">
                <Link href="/pages" className="text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300">
                  {ui(locale, 'Pages一覧を開く', 'Open Pages directory')}
                </Link>
                <Link href="/pages/deploy" className="text-indigo-700 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300">
                  {ui(locale, '公開方法を見る', 'View publishing flow')}
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
