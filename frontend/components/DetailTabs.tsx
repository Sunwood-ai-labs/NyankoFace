import Link from 'next/link';
import HfIcon from './HfIcon';
import type { RepoKind } from '@/lib/forgejo';
import { Locale, ui } from '@/lib/i18n';

export default function DetailTabs({
  owner,
  repo,
  active,
  isSpace,
  kind,
  communityCount,
  revision,
  locale,
}: {
  owner: string;
  repo: string;
  active: 'card' | 'files' | 'pipelines';
  isSpace?: boolean;
  kind?: RepoKind | null;
  communityCount?: number;
  revision?: string | null;
  locale: Locale;
}) {
  const filesHref = revision
    ? `/git/${owner}/${repo}/src/tag/${encodeURIComponent(revision)}`
    : `/git/${owner}/${repo}/src/branch/main`;
  const cardHref = revision
    ? `/${owner}/${repo}?revision=${encodeURIComponent(revision)}`
    : `/${owner}/${repo}?tab=card`;
  const cardLabel = isSpace
    ? 'App'
    : kind === 'dataset'
      ? ui(locale, 'データセットカード', 'Dataset card')
      : kind === 'skill'
        ? ui(locale, 'スキルカード', 'Skill card')
        : kind === 'mcp'
          ? 'MCP card'
          : kind === 'prompt'
            ? ui(locale, 'プロンプトカード', 'Prompt card')
          : kind === 'doc'
            ? ui(locale, 'ナレッジ', 'Knowledge')
          : kind === 'character'
            ? ui(locale, 'キャラクターカード', 'Character card')
          : kind === 'benchmark'
            ? ui(locale, 'ベンチマークカード', 'Benchmark card')
          : kind === 'automation'
            ? ui(locale, 'Automationカード', 'Automation card')
          : kind == null
            ? ui(locale, 'リポジトリ', 'Repository')
          : ui(locale, 'モデルカード', 'Model card');
  const tabClass = (tab: string) =>
    `inline-flex min-h-12 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2 text-sm font-semibold max-sm:gap-1 max-sm:px-2 max-sm:text-xs ${
      active === tab
        ? 'border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100'
        : 'border-transparent text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'
    }`;

  return (
    <div className="flex min-w-0 max-w-full shrink-0 gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden max-sm:w-full max-sm:justify-start max-sm:gap-0">
      <Link href={cardHref} className={tabClass('card')}>
        <HfIcon name={isSpace ? 'space' : kind === 'character' ? 'character' : kind === 'benchmark' ? 'benchmark' : kind === 'automation' ? 'automation' : kind == null ? 'folder' : 'file'} className="h-3.5 w-3.5" />
        {cardLabel}
      </Link>
      <a href={filesHref} className={tabClass('files')}>
        <HfIcon name="folder" className="h-3.5 w-3.5" />
        {ui(locale, 'ファイル', 'Files')}
      </a>
      <a href={`/git/${owner}/${repo}/issues`} className={tabClass('community')}>
        <HfIcon name="link" className="h-3.5 w-3.5" />
        {ui(locale, 'コミュニティ', 'Community')}
        {typeof communityCount === 'number' && communityCount > 0 ? (
          <span className="ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-zinc-100 px-1.5 text-xs font-semibold text-zinc-500">
            {communityCount}
          </span>
        ) : null}
      </a>
      <Link href={`/${owner}/${repo}?tab=pipelines`} className={tabClass('pipelines')}>
        <HfIcon name="code" className="h-3.5 w-3.5" />
        {ui(locale, 'パイプライン', 'Pipelines')}
      </Link>
    </div>
  );
}
