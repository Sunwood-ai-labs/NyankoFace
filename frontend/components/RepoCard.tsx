import Link from 'next/link';
import { Repo, nonTypeTopics, repoPromptVersion } from '@/lib/forgejo';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import { Locale, ui } from '@/lib/i18n';
import { getSpaceTheme } from '@/lib/space-theme';
import HfIcon, { HfIconName } from './HfIcon';

const KIND_ICON: Record<string, HfIconName> = {
  model: 'model',
  dataset: 'dataset',
  space: 'space',
  skill: 'skill',
  mcp: 'mcp',
  prompt: 'prompt',
};

const KIND_THEME = {
  model: {
    card: 'border-zinc-200 bg-white hover:border-zinc-300 hover:shadow-zinc-200/70',
    icon: 'bg-amber-100 text-amber-700 ring-amber-200',
    badge: 'bg-zinc-50 text-amber-800 ring-zinc-200 hover:bg-zinc-100',
    title: 'text-amber-800 hover:text-amber-950',
  },
  space: {
    card: 'border-indigo-200/80 bg-white hover:border-indigo-400 hover:shadow-indigo-100/80',
    icon: 'bg-indigo-100 text-indigo-700 ring-indigo-200',
    badge: 'bg-indigo-50 text-indigo-800 ring-indigo-200 hover:bg-indigo-100',
    title: 'text-indigo-800 hover:text-indigo-950',
  },
  dataset: {
    card: 'border-zinc-200 bg-white hover:border-zinc-300 hover:shadow-zinc-200/70',
    icon: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
    badge: 'bg-zinc-50 text-emerald-800 ring-zinc-200 hover:bg-zinc-100',
    title: 'text-emerald-800 hover:text-emerald-950',
  },
  skill: {
    card: 'border-violet-200/80 bg-white hover:border-violet-400 hover:shadow-violet-100/80',
    icon: 'bg-violet-100 text-violet-700 ring-violet-200',
    badge: 'bg-violet-50 text-violet-800 ring-violet-200 hover:bg-violet-100',
    title: 'text-violet-800 hover:text-violet-950',
  },
  mcp: {
    card: 'border-cyan-200/80 bg-white hover:border-cyan-400 hover:shadow-cyan-100/80',
    icon: 'bg-cyan-100 text-cyan-700 ring-cyan-200',
    badge: 'bg-cyan-50 text-cyan-800 ring-cyan-200 hover:bg-cyan-100',
    title: 'text-cyan-800 hover:text-cyan-950',
  },
  prompt: {
    card: 'border-orange-200/90 bg-white hover:border-orange-400 hover:shadow-orange-100/80',
    icon: 'bg-orange-100 text-orange-700 ring-orange-200',
    badge: 'bg-orange-50 text-orange-800 ring-orange-200 hover:bg-orange-100',
    title: 'text-orange-800 hover:text-orange-950',
  },
  default: {
    card: 'border-zinc-200 bg-white hover:border-amber-400',
    icon: 'bg-zinc-100 text-zinc-600 ring-zinc-200',
    badge: 'bg-zinc-100 text-zinc-600 ring-zinc-200 hover:bg-zinc-200',
    title: 'text-zinc-900',
  },
};

export default function RepoCard({ repo, kind, locale }: { repo: Repo; kind?: 'model' | 'dataset' | 'space' | 'skill' | 'mcp' | 'prompt'; locale: Locale }) {
  const owner = repo.owner?.login ?? repo.full_name.split('/')[0];
  const name = repo.name;
  const badges = nonTypeTopics(repo.topics).slice(0, 4);
  const promptVersion = kind === 'prompt' ? repoPromptVersion(repo.topics) : null;
  const icon = kind ? KIND_ICON[kind] : 'box';
  const basePath = kind === 'dataset' ? '/datasets' : kind === 'space' ? '/spaces' : kind === 'skill' ? '/skills' : kind === 'mcp' ? '/mcps' : kind === 'prompt' ? '/prompts' : '/models';
  const theme = kind ? KIND_THEME[kind] : KIND_THEME.default;
  const spaceTheme = getSpaceTheme(repo.full_name);

  return (
    <article className={`group relative flex min-w-0 min-h-44 flex-col overflow-hidden rounded-xl border shadow-sm transition duration-200 hover:-translate-y-0.5 hover:shadow-lg dark:border-zinc-800 dark:bg-zinc-900 ${kind === 'space' ? 'p-0' : 'p-4'} ${theme.card}`}>
      {kind === 'space' ? (
        <Link
          href={`/${owner}/${name}`}
          className={`relative flex h-24 shrink-0 items-center justify-center overflow-hidden bg-gradient-to-br ${spaceTheme.gradient}`}
          aria-label={ui(locale, `${repo.full_name}を開く`, `Open ${repo.full_name}`)}
        >
          <span className={`absolute -left-8 -top-12 h-28 w-28 rounded-full opacity-60 blur-2xl ${spaceTheme.glow}`} />
          <span className="absolute -bottom-16 -right-8 h-32 w-32 rounded-full bg-white/25 blur-2xl" />
          <span className="absolute inset-0 opacity-25 [background-image:linear-gradient(rgba(255,255,255,.35)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.35)_1px,transparent_1px)] [background-size:18px_18px]" />
          <span className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-white/20 text-2xl text-white shadow-lg ring-1 ring-white/35 backdrop-blur-sm transition duration-300 group-hover:scale-110 group-hover:rotate-3">
            <span role="img" aria-label={`${name} icon`}>{repo.space_emoji || '🚀'}</span>
          </span>
          <span className="absolute bottom-2.5 left-3 rounded-full bg-black/20 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.16em] text-white/90 backdrop-blur-sm">
            NyankoFace Space
          </span>
          <HfIcon name="space" className="absolute right-3 top-3 h-3.5 w-3.5 text-white/80 transition-transform duration-300 group-hover:-translate-y-1 group-hover:translate-x-1" />
        </Link>
      ) : null}

      <div className={`flex flex-1 flex-col ${kind === 'space' ? 'p-4' : ''}`}>
        <div className="flex min-w-0 items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2 truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ring-1 ${theme.icon}`}>
              <HfIcon name={icon} className="h-3 w-3" />
            </span>
            <a href={`/git/${owner}`} className="min-w-0 max-w-[42%] truncate text-zinc-500 hover:text-zinc-900 hover:underline dark:text-zinc-400" title={owner}>
              {owner}/
            </a>
            <Link href={`/${owner}/${name}`} className={`min-w-0 flex-1 truncate hover:underline ${theme.title}`} title={name}>
              {name}
            </Link>
          </div>
          {promptVersion ? (
            <Link href={`${basePath}?q=${encodeURIComponent(`version-${promptVersion}`)}`} className="shrink-0 rounded-full border border-orange-200 bg-orange-50 px-2 py-0.5 font-mono text-[11px] font-bold text-orange-800 transition hover:bg-orange-100">
              {promptVersion}
            </Link>
          ) : null}
        </div>

        <Link href={`/${owner}/${name}`} className="mt-2 line-clamp-2 min-h-[2.5rem] min-w-0 text-sm text-zinc-600 [overflow-wrap:anywhere] hover:text-zinc-900 dark:text-zinc-400">
          {repo.description || ui(locale, '説明はありません', 'No description')}
        </Link>

        {badges.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {badges.map((t) => (
              <Link
                key={t}
                href={`${basePath}?q=${encodeURIComponent(t)}`}
                className={`max-w-full rounded-md px-2 py-0.5 text-xs [overflow-wrap:anywhere] ring-1 ring-inset transition-colors dark:bg-zinc-800 dark:text-zinc-300 ${theme.badge}`}
              >
                {t}
              </Link>
            ))}
          </div>
        )}

        <div className="mt-auto flex items-center gap-3 pt-3 text-xs text-zinc-500 dark:text-zinc-400">
          <a
            href={`/git/${owner}/${name}`}
            className="inline-flex items-center gap-1 hover:text-zinc-900"
            title={repo.stars_count == null ? ui(locale, 'スター数は未集計です', 'Star count is unavailable') : ui(locale, `Forgejoスター ${repo.stars_count}件`, `${repo.stars_count} Forgejo stars`)}
            data-metric-state={repo.stars_count == null ? 'unavailable' : 'available'}
          >
            <HfIcon name="star" className="h-3 w-3" />{repo.stars_count ?? '—'}
          </a>
          <a
            href={`/git/${owner}/${name}/forks`}
            className="inline-flex items-center gap-1 hover:text-zinc-900"
            title={repo.forks_count == null ? ui(locale, 'フォーク数は未集計です', 'Fork count is unavailable') : ui(locale, `Forgejoフォーク ${repo.forks_count}件`, `${repo.forks_count} Forgejo forks`)}
            data-metric-state={repo.forks_count == null ? 'unavailable' : 'available'}
          >
            <HfIcon name="fork" className="h-3 w-3" />{repo.forks_count ?? '—'}
          </a>
          <span className="ml-auto">{locale === 'ja' ? timeAgoJa(repo.updated_at) : timeAgoEn(repo.updated_at)}</span>
        </div>
      </div>
    </article>
  );
}
