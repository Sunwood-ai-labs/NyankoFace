import { type CatalogSort, type SortOrder } from '@/lib/catalog-sort';
import { type Locale, ui } from '@/lib/i18n';
import HfIcon from './HfIcon';

const labels: Record<CatalogSort, { ja: string; en: string }> = {
  created: { ja: '新着', en: 'Created' },
  updated: { ja: '更新', en: 'Updated' },
  likes: { ja: 'いいね', en: 'Likes' },
  views: { ja: '閲覧数', en: 'Views' },
};

export function CatalogOrderingInputs({ sort, order }: { sort: CatalogSort; order: SortOrder }) {
  return (
    <>
      <input type="hidden" name="sort" value={sort} />
      <input type="hidden" name="order" value={order} />
    </>
  );
}

export default function CatalogSortControl({
  action,
  locale,
  order,
  preserve = {},
  sort,
}: {
  action: string;
  locale: Locale;
  order: SortOrder;
  preserve?: Record<string, string | undefined>;
  sort: CatalogSort;
}) {
  return (
    <form action={action} method="get" className="flex min-w-0 flex-wrap items-center gap-2" aria-label={ui(locale, '並び順', 'Sort order')}>
      {Object.entries(preserve).map(([name, value]) => value ? <input key={name} type="hidden" name={name} value={value} /> : null)}
      <label className="sr-only" htmlFor={`${action}-sort`.replace(/\W/g, '-')}>{ui(locale, '並び替え基準', 'Sort by')}</label>
      <select
        id={`${action}-sort`.replace(/\W/g, '-')}
        name="sort"
        defaultValue={sort}
        className="h-[34px] min-w-24 rounded-full border border-zinc-200 bg-white px-3 text-xs font-semibold text-zinc-700 shadow-sm outline-none focus:border-zinc-400 focus:ring-2 focus:ring-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:focus:ring-zinc-800 sm:text-sm"
      >
        {Object.entries(labels).map(([value, label]) => (
          <option key={value} value={value}>{locale === 'ja' ? label.ja : label.en}</option>
        ))}
      </select>
      <label className="sr-only" htmlFor={`${action}-order`.replace(/\W/g, '-')}>{ui(locale, '昇順または降順', 'Ascending or descending')}</label>
      <select
        id={`${action}-order`.replace(/\W/g, '-')}
        name="order"
        defaultValue={order}
        className="h-[34px] min-w-20 rounded-full border border-zinc-200 bg-white px-3 text-xs font-semibold text-zinc-700 shadow-sm outline-none focus:border-zinc-400 focus:ring-2 focus:ring-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:focus:ring-zinc-800 sm:text-sm"
      >
        <option value="desc">{ui(locale, '多い／新しい順', 'High / new first')}</option>
        <option value="asc">{ui(locale, '少ない／古い順', 'Low / old first')}</option>
      </select>
      <button type="submit" className="inline-flex h-[34px] items-center gap-1.5 rounded-full bg-zinc-900 px-3 text-xs font-bold text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-950 sm:text-sm">
        <HfIcon name="sort" className="h-3 w-3" />
        {ui(locale, '適用', 'Apply')}
      </button>
    </form>
  );
}
