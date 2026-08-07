import { Repo } from '@/lib/forgejo';
import RepoCard from './RepoCard';
import { Locale, ui } from '@/lib/i18n';

export default function RepoGrid({
  repos,
  kind,
  emptyMessage,
  locale,
}: {
  repos: Repo[];
  kind?: 'model' | 'dataset' | 'space' | 'skill' | 'mcp' | 'prompt';
  emptyMessage?: string;
  locale: Locale;
}) {
  if (!repos || repos.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 p-10 text-center text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
        {emptyMessage || ui(locale, 'リポジトリが見つかりません。', 'No repositories found.')}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {repos.map((repo) => (
        <RepoCard key={repo.id ?? repo.full_name} repo={repo} kind={kind} locale={locale} />
      ))}
    </div>
  );
}
