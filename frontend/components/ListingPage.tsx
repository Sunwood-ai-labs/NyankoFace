import { RepoKind } from '@/lib/forgejo';
import { getCatalogPage, isCatalogSort, isSortOrder, type CatalogSort, type SortOrder } from '@/lib/catalog-sort';
import HfIcon, { HfIconName } from './HfIcon';
import FilterRail from './FilterRail';
import RepoSearchList from './RepoSearchList';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import Link from 'next/link';
import CatalogSortControl from './CatalogSortControl';

const PAGE_SIZE = 48;

export interface ListingPageProps {
  topic: RepoKind;
  title: string;
  icon: HfIconName;
  placeholder: string;
  searchParams?: { q?: string; sort?: string; order?: string; page?: string };
}

export default async function ListingPage({
  topic,
  title,
  icon,
  placeholder,
  searchParams,
}: ListingPageProps) {
  const locale = await getLocale();
  const q = searchParams?.q?.trim() || undefined;
  const sort: CatalogSort = isCatalogSort(searchParams?.sort) ? searchParams.sort : 'updated';
  const order: SortOrder = isSortOrder(searchParams?.order) ? searchParams.order : 'desc';
  const requestedPage = Number.parseInt(searchParams?.page || '1', 10);
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const basePath = `/${topic}s`;
  const filterHref = (term: string) => `${basePath}?q=${encodeURIComponent(term)}&sort=${sort}&order=${order}`;

  const result = await getCatalogPage({ topic, q, sort, order, page, limit: PAGE_SIZE });
  const currentPage = result.page;
  const promptVersionTopics = topic === 'prompt' && result.ok
    ? Array.from(new Set(result.data.flatMap((repo) => (repo.topics || []).filter((repoTopic) => /^version-v\d+(?:\.\d+)*$/i.test(repoTopic)))))
      .sort((left, right) => left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' }))
    : [];
  const iconTone = topic === 'dataset' ? 'text-emerald-600' : topic === 'skill' ? 'text-violet-600' : topic === 'mcp' ? 'text-cyan-600' : topic === 'prompt' ? 'text-orange-600' : topic === 'benchmark' ? 'text-sky-600' : topic === 'automation' ? 'text-amber-800' : 'text-amber-600';
  const createLabel = topic === 'dataset' ? ui(locale, 'データセット', 'Dataset') : topic === 'space' ? 'Space' : topic === 'skill' ? ui(locale, 'スキル', 'Skill') : topic === 'mcp' ? 'MCP server' : topic === 'prompt' ? ui(locale, 'プロンプト', 'Prompt') : topic === 'benchmark' ? ui(locale, 'ベンチマーク', 'Benchmark') : topic === 'automation' ? 'Automation' : ui(locale, 'モデル', 'Model');
  const mobileFilters: Array<{ label: string; query?: string }> = topic === 'dataset'
    ? ['Audio', 'Image', 'Text', 'Tabular', 'parquet', 'Benchmark'].map((label) => ({ label }))
    : topic === 'skill'
      ? ['Codex', 'Automation', 'Design', 'Developer tools', 'Workflow'].map((label) => ({ label }))
      : topic === 'mcp'
        ? ['TypeScript', 'Python', 'API', 'Search', 'Developer tools'].map((label) => ({ label }))
        : topic === 'prompt'
          ? [
              ...['Goal command', 'Coding agent', 'Workflow'].map((label) => ({ label })),
              ...promptVersionTopics.map((versionTopic) => ({ label: versionTopic.replace(/^version-/, ''), query: versionTopic })),
            ]
        : topic === 'benchmark'
          ? ['CAD', 'SVG', 'Text-to-CAD', 'Generation', 'Editing', 'CPU', 'Executable tests'].map((label) => ({ label }))
        : topic === 'automation'
          ? ['Scheduled', 'Manual', 'Repository', 'Reporting', 'No write access', 'Codex'].map((label) => ({ label }))
        : ['Text Generation', 'Image-to-Text', 'Safetensors', 'Transformers', 'GGUF', 'vLLM'].map((label) => ({ label }));

  return (
    <div className="mx-auto grid min-w-0 max-w-[1536px] gap-8 px-4 lg:grid-cols-[422px_minmax(0,1fr)]">
      <FilterRail topic={topic === 'space' ? 'model' : topic} promptVersionTopics={promptVersionTopics} locale={locale} />
      <div className="min-w-0 lg:pt-[34px]">
        <div className="mb-6 flex min-w-0 flex-wrap items-center gap-3">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <HfIcon name={icon} className={`h-5 w-5 ${iconTone}`} />
            {title}
          </h1>
          <span className="text-zinc-400">{result.ok ? result.totalCount : 0}</span>
          <form action={`/${topic}s`} method="get" className="relative ml-4 hidden w-[224px] lg:block">
            <input
              type="text"
              name="q"
              defaultValue={q}
              placeholder={placeholder}
              className="h-7 w-full rounded-full border border-zinc-200 px-3 pl-9 text-sm placeholder-zinc-400 shadow-sm focus:border-zinc-300 focus:outline-none focus:ring-2 focus:ring-zinc-100"
            />
            <HfIcon name="search" className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
            <input type="hidden" name="sort" value={sort} />
            <input type="hidden" name="order" value={order} />
          </form>
          <form action={`/${topic}s`} method="get" className="relative order-3 ml-0 w-full lg:order-none lg:hidden">
            <input
              type="text"
              name="q"
              defaultValue={q}
              placeholder={placeholder}
              className="h-7 w-full rounded-full border border-zinc-200 px-4 pl-10 text-sm placeholder-zinc-400 focus:border-zinc-300 focus:outline-none focus:ring-2 focus:ring-zinc-100"
            />
            <HfIcon name="search" className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
            <input type="hidden" name="sort" value={sort} />
            <input type="hidden" name="order" value={order} />
          </form>
          <div className="order-4 ml-0 flex w-full min-w-0 flex-row flex-wrap gap-2 sm:order-2 sm:ml-auto sm:w-auto sm:justify-end lg:order-none lg:gap-2">
            <Link
              href={`/new?type=${topic}`}
              className="hidden w-full rounded-lg bg-zinc-950 px-4 py-2 text-center text-sm font-semibold text-white hover:bg-zinc-800 sm:w-auto"
            >
              {ui(locale, `新規${createLabel}`, `New ${createLabel}`)}
            </Link>
            {topic === 'model' && <Link href={filterHref('base')} className="inline-flex h-[30px] w-auto items-center rounded-full border border-zinc-200 px-3 text-center text-sm text-zinc-600 hover:bg-zinc-50">{ui(locale, 'ベースのみ', 'Base only')}</Link>}
            {topic === 'model' && <Link href={filterHref('inference')} className="inline-flex h-[30px] w-auto items-center rounded-full border border-zinc-200 px-3 text-center text-sm text-zinc-600 hover:bg-zinc-50">{ui(locale, '推論対応', 'Inference available')}</Link>}
            {topic === 'dataset' && <Link href={filterHref(q || 'text')} className="inline-flex h-[30px] w-auto items-center rounded-full border border-zinc-200 px-3 text-center text-sm text-zinc-600 hover:bg-zinc-50">{ui(locale, '全文検索', 'Full-text search')}</Link>}
            <details name={`${topic}-add-filter-menu`} className="group relative w-auto lg:hidden">
              <summary className="inline-flex h-[30px] w-auto cursor-pointer list-none items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm text-zinc-600 marker:hidden hover:bg-zinc-50 [&::-webkit-details-marker]:hidden">
                <HfIcon name="sliders" className="h-3.5 w-3.5" />
                {ui(locale, 'フィルターを追加', 'Add filters')}
              </summary>
              <div className="absolute left-0 right-auto z-20 mt-2 hidden w-full rounded-lg border border-zinc-200 bg-white p-2 text-sm shadow-lg group-open:grid sm:left-auto sm:right-0 sm:w-56">
                {mobileFilters.map((item) => (
                  <Link key={item.query || item.label} href={filterHref(item.query || item.label)} className="rounded-lg px-3 py-2 text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900">
                    {item.label}
                  </Link>
                ))}
              </div>
            </details>
            <CatalogSortControl action={basePath} locale={locale} order={order} preserve={{ q }} sort={sort} />
          </div>
        </div>

        {!result.ok ? (
          <div className="rounded-lg border border-dashed border-zinc-300 p-10 text-center text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
            {ui(locale, 'Forgejoに接続できませんでした。しばらくしてから再度お試しください。', 'Could not connect to Forgejo. Please try again shortly.')}
          </div>
        ) : (
          <RepoSearchList
            repos={result.data}
            kind={topic === 'dataset' ? 'dataset' : topic === 'skill' ? 'skill' : topic === 'mcp' ? 'mcp' : topic === 'prompt' ? 'prompt' : topic === 'benchmark' ? 'benchmark' : topic === 'automation' ? 'automation' : 'model'}
            emptyMessage={ui(locale, `${title}はまだありません。`, `No ${title.toLowerCase()} yet.`)}
            locale={locale}
            sort={sort}
            order={order}
          />
        )}
        {result.ok && result.totalPages > 1 ? (
          <nav aria-label={ui(locale, `${title}のページ送り`, `${title} pagination`)} className="mt-7 flex items-center justify-end gap-2 pb-8">
            {currentPage > 1 ? <Link href={`${basePath}?${new URLSearchParams({ ...(q ? { q } : {}), sort, order, page: String(currentPage - 1) })}`} className="rounded-full border border-zinc-200 px-4 py-2 text-sm font-semibold">{ui(locale, '前へ', 'Previous')}</Link> : null}
            <span className="rounded-full bg-zinc-900 px-4 py-2 text-sm font-bold text-white">{currentPage} / {result.totalPages}</span>
            {currentPage < result.totalPages ? <Link href={`${basePath}?${new URLSearchParams({ ...(q ? { q } : {}), sort, order, page: String(currentPage + 1) })}`} className="rounded-full border border-zinc-200 px-4 py-2 text-sm font-semibold">{ui(locale, '次へ', 'Next')}</Link> : null}
          </nav>
        ) : null}
      </div>
    </div>
  );
}
