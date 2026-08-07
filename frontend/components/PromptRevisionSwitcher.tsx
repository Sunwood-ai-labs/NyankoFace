import HfIcon from './HfIcon';
import type { RepoTag } from '@/lib/forgejo';
import { Locale, ui } from '@/lib/i18n';

export default function PromptRevisionSwitcher({
  owner,
  repo,
  tags,
  selectedRevision,
  locale,
}: {
  owner: string;
  repo: string;
  tags: RepoTag[];
  selectedRevision: string | null;
  locale: Locale;
}) {
  const basePath = `/${owner}/${repo}`;

  return (
    <section className="mt-4 overflow-hidden rounded-xl border border-orange-200 bg-[linear-gradient(110deg,#fff7ed_0%,#ffffff_48%,#fffbeb_100%)] shadow-[0_10px_30px_-24px_rgba(194,65,12,0.8)] dark:border-orange-950 dark:bg-[linear-gradient(110deg,rgba(124,45,18,0.22),rgba(24,24,27,0.9))]">
      <div className="flex flex-wrap items-center gap-3 border-b border-orange-100 px-4 py-3 dark:border-orange-950">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-orange-700 text-white shadow-sm">
          <HfIcon name="prompt" className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-orange-700 dark:text-orange-300">{ui(locale, '改訂履歴', 'Revision history')}</p>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            {selectedRevision ? ui(locale, `固定されたGitタグ ${selectedRevision} を表示中`, `Viewing immutable Git tag ${selectedRevision}`) : ui(locale, '最新のデフォルトブランチを表示中', 'Viewing the latest default branch')}
          </p>
        </div>
        {selectedRevision ? (
          <a href={basePath} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-orange-200 bg-white px-3 text-xs font-semibold text-orange-800 transition hover:-translate-y-0.5 hover:shadow-sm dark:border-orange-900 dark:bg-zinc-900 dark:text-orange-200">
            <HfIcon name="arrowRight" className="h-3 w-3 rotate-180" /> {ui(locale, '最新', 'Latest')}
          </a>
        ) : null}
      </div>
      <nav aria-label={ui(locale, 'プロンプトの改訂', 'Prompt revision')} className="flex flex-wrap items-center gap-2 px-4 py-3">
        <a
          href={basePath}
          aria-current={selectedRevision === null ? 'page' : undefined}
          className={`inline-flex h-8 items-center gap-2 rounded-full px-3 text-xs font-bold transition ${selectedRevision === null ? 'bg-zinc-950 text-white shadow-sm dark:bg-white dark:text-zinc-950' : 'border border-zinc-200 bg-white text-zinc-600 hover:border-orange-300 hover:text-orange-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300'}`}
        >
          {ui(locale, '最新', 'Latest')}
          {selectedRevision === null ? <span className="h-1.5 w-1.5 rounded-full bg-orange-400" /> : null}
        </a>
        {tags.map((tag) => {
          const active = selectedRevision === tag.name;
          return (
            <a
              key={tag.name}
              href={`${basePath}?revision=${encodeURIComponent(tag.name)}`}
              aria-current={active ? 'page' : undefined}
              title={tag.message || ui(locale, `${tag.name}を表示`, `View ${tag.name}`)}
              className={`inline-flex h-8 items-center gap-2 rounded-full px-3 font-mono text-xs font-bold transition ${active ? 'bg-orange-700 text-white shadow-sm ring-2 ring-orange-200 ring-offset-2 dark:ring-orange-950' : 'border border-orange-200 bg-white text-orange-800 hover:-translate-y-0.5 hover:bg-orange-50 hover:shadow-sm dark:border-orange-900 dark:bg-zinc-900 dark:text-orange-200'}`}
            >
              {tag.name}
              {active ? <span aria-hidden="true" className="text-[10px]">✓</span> : null}
            </a>
          );
        })}
      </nav>
    </section>
  );
}
