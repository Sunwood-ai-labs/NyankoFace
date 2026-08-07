import Link from 'next/link';
import HfIcon from '@/components/HfIcon';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';
import { getPagesInspection } from '@/lib/forgejo';
import { getCatalogPage, isCatalogSort, isSortOrder, type CatalogSort, type SortOrder } from '@/lib/catalog-sort';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import CatalogSortControl from '@/components/CatalogSortControl';

const PAGE_SIZE = 36;

export const dynamic = 'force-dynamic';

export async function generateMetadata() {
  const locale = await getLocale();
  return {
    title: `${ui(locale, 'Pages一覧', 'Pages directory')} - ${getAppName()}`,
  };
}

export default async function PagesDirectoryPage({
  searchParams,
}: {
  searchParams?: Promise<{ q?: string; sort?: string; order?: string; page?: string }>;
}) {
  const locale = await getLocale();
  const params = await searchParams;
  const q = params?.q?.trim() || undefined;
  const sort: CatalogSort = isCatalogSort(params?.sort) ? params.sort : 'updated';
  const order: SortOrder = isSortOrder(params?.order) ? params.order : 'desc';
  const requestedPage = Number.parseInt(params?.page || '1', 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const result = await getCatalogPage({ q, sort, order, page, limit: PAGE_SIZE });
  const currentPage = result.page;
  const candidates = result.ok ? result.data : [];
  const inspections = await Promise.all(
    candidates.map(async (repo) => {
      const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
      const inspection = await getPagesInspection(owner, repo.name);
      return { repo, owner, inspection };
    }),
  );
  const publishedCount = inspections.filter((item) => item.inspection.status === 'published').length;
  const pageHref = (targetPage: number) => {
    const query = new URLSearchParams({ sort, order, page: String(targetPage) });
    if (q) query.set('q', q);
    return `/pages?${query}`;
  };

  return (
    <main className="mx-auto w-full max-w-[1536px] px-4 py-8" data-pages-directory>
      <header className="flex flex-col items-start gap-5 border-b border-zinc-200 pb-6 sm:flex-row dark:border-zinc-800">
        <div className="w-full min-w-0 sm:flex-1">
          <p className="nyankoface-pages-kicker flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-300">
            <HfIcon name="pages" className="h-3.5 w-3.5" />
            NyankoFace Pages
          </p>
          <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-zinc-950 dark:text-white">
            {ui(locale, '静的サイト一覧', 'Static site directory')}
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-zinc-600 dark:text-zinc-300">
            {ui(
              locale,
              `このページでは${publishedCount}件を公開中。Pagesにtopicは不要です。未設定のpublicリポジトリもここから公開を開始できます。`,
              `${publishedCount} published on this page. Pages requires no topic, and any unconfigured public repository can start here.`,
            )}
          </p>
        </div>
        <Link href="/pages/deploy" className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-full bg-indigo-700 px-5 text-sm font-bold text-white shadow-sm hover:bg-indigo-800 sm:w-auto">
          <HfIcon name="plus" className="h-3.5 w-3.5" />
          {ui(locale, '新しいPagesをデプロイ', 'Deploy new Pages')}
        </Link>
      </header>

      <form action="/pages" method="get" className="relative mt-6 max-w-xl">
        <HfIcon name="search" className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
        <input
          type="search"
          name="q"
          defaultValue={q}
          placeholder={ui(locale, 'publicリポジトリを検索', 'Search public repositories')}
          className="h-11 w-full rounded-full border border-zinc-200 bg-white pl-11 pr-4 text-sm text-zinc-950 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-white dark:focus:ring-indigo-950"
        />
        <input type="hidden" name="sort" value={sort} />
        <input type="hidden" name="order" value={order} />
      </form>
      <div className="mt-4 flex justify-end">
        <CatalogSortControl action="/pages" locale={locale} order={order} preserve={{ q }} sort={sort} />
      </div>

      {!result.ok ? (
        <section className="mt-8 rounded-2xl border border-dashed border-rose-300 bg-rose-50 p-8 text-center text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
          <p className="font-bold">{ui(locale, 'Forgejoへ接続できませんでした。', 'Could not connect to Forgejo.')}</p>
          <p className="mt-2 text-sm">{ui(locale, '接続を確認してから再読み込みしてください。', 'Check the connection and reload this page.')}</p>
        </section>
      ) : inspections.length === 0 ? (
        <section className="mt-8 rounded-2xl border border-dashed border-zinc-300 p-10 text-center dark:border-zinc-700">
          <HfIcon name="pages" className="mx-auto h-8 w-8 text-indigo-400" />
          <h2 className="mt-4 text-lg font-bold text-zinc-950 dark:text-white">{ui(locale, '公開できるリポジトリがまだありません', 'No repository is ready yet')}</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-zinc-500 dark:text-zinc-400">{ui(locale, 'publicリポジトリを作成してから、静的HTMLまたはVitePressの公開方式を選んでください。', 'Create a public repository, then choose static HTML or VitePress publishing.')}</p>
          <Link href="/new?type=pages" className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-indigo-700 px-4 text-sm font-bold text-white">
            <HfIcon name="plus" className="h-3.5 w-3.5" />
            {ui(locale, 'Pagesを始める', 'Start Pages')}
          </Link>
        </section>
      ) : (
        <section className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {inspections.map(({ repo, owner, inspection }) => {
            const published = inspection.status === 'published';
            return (
              <article key={repo.full_name} className="flex min-h-64 flex-col rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900" data-pages-card-status={inspection.status}>
                <div className="flex items-start justify-between gap-3">
                  <span className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                    published
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
                      : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-300'
                  }`}>
                    <HfIcon name="pages" className="h-4 w-4" />
                  </span>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
                    published
                      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                      : inspection.status === 'error'
                        ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                        : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
                  }`}>
                    {published
                      ? ui(locale, '公開中', 'Published')
                      : inspection.status === 'error'
                        ? ui(locale, '確認エラー', 'Inspection error')
                        : ui(locale, '未設定', 'Not configured')}
                  </span>
                </div>
                <Link href={`/${owner}/${repo.name}`} className="mt-4 break-words font-mono text-base font-bold text-zinc-950 hover:underline dark:text-white">
                  {repo.full_name}
                </Link>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-zinc-500 dark:text-zinc-400">{repo.description || ui(locale, '説明はありません。', 'No description.')}</p>
                <div className="mt-3 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
                  {published ? (
                    <p>{ui(locale, '配信元: ', 'Source: ')}<code>{inspection.index_path}</code></p>
                  ) : (
                    <p>{ui(locale, '必要: gh-pages/index.html または default branch/docs/index.html', 'Needs gh-pages/index.html or default-branch/docs/index.html')}</p>
                  )}
                  <p className="mt-1">{locale === 'ja' ? timeAgoJa(repo.updated_at) : timeAgoEn(repo.updated_at)}</p>
                  <p className="mt-1 flex items-center gap-3">
                    <span className="inline-flex items-center gap-1"><HfIcon name="heart" className="h-3 w-3" />{repo.metrics.availability === 'available' ? repo.metrics.likes : '—'}</span>
                    <span className="inline-flex items-center gap-1"><HfIcon name="eye" className="h-3 w-3" />{repo.metrics.availability === 'available' ? repo.metrics.views : '—'}</span>
                  </p>
                </div>
                <div className="mt-auto grid gap-2 pt-5 sm:grid-cols-2">
                  {published ? (
                    <a href={inspection.public_url || '#'} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-indigo-700 px-3 text-sm font-bold text-white hover:bg-indigo-800">
                      <HfIcon name="external" className="h-3.5 w-3.5" />
                      {ui(locale, 'サイトを見る', 'Visit site')}
                    </a>
                  ) : (
                    <Link href={`/pages/deploy?owner=${encodeURIComponent(owner)}&repo=${encodeURIComponent(repo.name)}`} className="nyankoface-pages-primary inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-bold text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-950">
                      <HfIcon name="pages" className="h-3.5 w-3.5" />
                      {ui(locale, '公開する', 'Deploy')}
                    </Link>
                  )}
                  <Link href={`/${owner}/${repo.name}`} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800">
                    {ui(locale, 'リポジトリ', 'Repository')}
                    <HfIcon name="arrowRight" className="h-3 w-3" />
                  </Link>
                </div>
              </article>
            );
          })}
        </section>
      )}
      {result.ok && result.totalPages > 1 ? (
        <nav aria-label={ui(locale, 'Pagesのページ送り', 'Pages pagination')} className="mt-7 flex items-center justify-end gap-2">
          {currentPage > 1 ? <Link href={pageHref(currentPage - 1)} className="rounded-full border border-zinc-200 px-4 py-2 text-sm font-semibold">{ui(locale, '前へ', 'Previous')}</Link> : null}
          <span className="rounded-full bg-zinc-900 px-4 py-2 text-sm font-bold text-white dark:bg-zinc-100 dark:text-zinc-950">{currentPage} / {result.totalPages}</span>
          {currentPage < result.totalPages ? <Link href={pageHref(currentPage + 1)} className="rounded-full border border-zinc-200 px-4 py-2 text-sm font-semibold">{ui(locale, '次へ', 'Next')}</Link> : null}
        </nav>
      ) : null}
    </main>
  );
}
