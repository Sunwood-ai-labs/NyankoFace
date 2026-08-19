import Link from 'next/link';
import {
  CommitInfo,
  ContentEntry,
  forgejoCommitsUrl,
  nyankofaceDownloadUrl,
  forgejoTreeUrl,
} from '@/lib/forgejo';
import { formatBytes } from '@/lib/format';
import HfIcon, { HfIconName } from './HfIcon';
import DownloadLink from './DownloadLink';
import { Locale, ui } from '@/lib/i18n';

function icon(entry: ContentEntry): HfIconName {
  if (entry.type === 'dir') return 'folder';
  if (entry.type === 'submodule') return 'link';
  const ext = entry.name.split('.').pop()?.toLowerCase();
  if (ext === 'md') return 'filePen';
  if (ext && ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'image';
  if (ext && ['json', 'yaml', 'yml', 'toml'].includes(ext)) return 'gear';
  if (ext && ['bin', 'safetensors', 'pt', 'ckpt', 'onnx', 'gguf'].includes(ext)) return 'model';
  if (ext && ['csv', 'parquet', 'tsv'].includes(ext)) return 'dataset';
  return 'file';
}

export default function FileTree({
  owner,
  repo,
  currentPath,
  entries,
  branch,
  commits,
  updatedAt,
  forgejoUrl,
  cloneUrl,
  refKind = 'branch',
  revision,
  locale,
}: {
  owner: string;
  repo: string;
  currentPath: string;
  entries: ContentEntry[];
  branch: string;
  commits: CommitInfo[];
  updatedAt: string;
  forgejoUrl: string;
  cloneUrl: string;
  refKind?: 'branch' | 'tag';
  revision?: string | null;
  locale: Locale;
}) {
  const sorted = [...entries].sort((a, b) => {
    if (a.type === 'dir' && b.type !== 'dir') return -1;
    if (a.type !== 'dir' && b.type === 'dir') return 1;
    return a.name.localeCompare(b.name);
  });

  const segments = currentPath.split('/').filter(Boolean);
  const latestCommit = commits[0];
  const latestMessage = latestCommit?.commit?.message?.split('\n')[0] || ui(locale, 'Forgejoから同期', 'Synced from Forgejo');
  const latestAuthor =
    latestCommit?.author?.login ||
    latestCommit?.commit?.author?.name ||
    latestCommit?.commit?.committer?.name ||
    owner;
  const latestDate =
    latestCommit?.commit?.committer?.date ||
    latestCommit?.commit?.author?.date ||
    updatedAt;
  const shortSha = latestCommit?.sha?.slice(0, 7);
  const totalSize = sorted.reduce((sum, entry) => sum + (entry.type === 'file' ? entry.size || 0 : 0), 0);
  const repositoryHref = revision
    ? `/${owner}/${repo}?tab=files&revision=${encodeURIComponent(revision)}`
    : `/${owner}/${repo}?tab=files`;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <a
          href={forgejoTreeUrl(owner, repo, currentPath, branch, refKind)}
          className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-700 shadow-sm hover:border-amber-400"
          title={ui(locale, 'このブランチをForgejoで開く', 'Open this branch in Forgejo')}
        >
          <HfIcon name="fork" className="h-3.5 w-3.5" />
          {branch}
        </a>

        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 text-sm text-zinc-500 dark:text-zinc-400">
          <Link href={repositoryHref} className="font-medium text-zinc-700 hover:underline">
            {repo}
          </Link>
          {segments.map((seg, idx) => {
            const pathSoFar = segments.slice(0, idx + 1).join('/');
            return (
              <span key={idx} className="flex items-center gap-1">
                <span>/</span>
                <a
                  href={forgejoTreeUrl(owner, repo, pathSoFar, branch, refKind)}
                  className="hover:text-amber-700 hover:underline"
                  title={ui(locale, 'このフォルダをForgejoで開く', 'Open this folder in Forgejo')}
                >
                  {seg}
                </a>
              </span>
            );
          })}
          <span className="ml-2 rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-500">
            {formatBytes(totalSize)}
          </span>
        </div>

        <details className="group relative w-full max-w-xs">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-500 shadow-sm marker:hidden hover:border-amber-400 [&::-webkit-details-marker]:hidden">
            <HfIcon name="search" className="h-3.5 w-3.5 text-zinc-400" />
            <span className="truncate">{ui(locale, 'ファイルへ移動', 'Go to file')}</span>
          </summary>
          <div className="absolute right-0 z-30 mt-2 max-h-80 w-full overflow-auto rounded-lg border border-zinc-200 bg-white p-2 text-sm shadow-xl">
            {sorted.length > 0 ? (
              sorted.map((entry) => {
                const isDir = entry.type === 'dir';
                const href = forgejoTreeUrl(owner, repo, entry.path, branch, refKind);
                return (
                  <a
                    key={`go-${entry.path}`}
                    href={href}
                    className="flex items-center gap-2 rounded-lg px-3 py-2 text-zinc-700 hover:bg-zinc-50"
                    title={ui(locale, 'Forgejoで開く', 'Open in Forgejo')}
                  >
                    <HfIcon name={icon(entry)} className="h-3.5 w-3.5 text-zinc-400" />
                    <span className="min-w-0 truncate">{entry.path}</span>
                  </a>
                );
              })
            ) : (
              <span className="block px-3 py-2 text-zinc-500">{ui(locale, 'このフォルダにファイルはありません', 'No files in this folder')}</span>
            )}
          </div>
        </details>

        <a
          href={forgejoCommitsUrl(owner, repo, currentPath, branch, refKind)}
          className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-700 shadow-sm"
        >
          <HfIcon name="clock" className="h-3.5 w-3.5" />
          {ui(locale, `履歴: ${commits.length || 0}コミット`, `History: ${commits.length || 0} commits`)}
        </a>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <table className="w-full text-sm">
          <tbody>
            <tr className="bg-zinc-50 text-zinc-600 dark:bg-zinc-900/70 dark:text-zinc-300">
              <td className="px-4 py-3" colSpan={4}>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-900 text-xs font-bold text-white">
                    {latestAuthor.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100">{latestAuthor}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-zinc-600">{latestMessage}</span>
                  {shortSha && (
                    <a
                      href={latestCommit?.html_url || forgejoCommitsUrl(owner, repo, currentPath, branch, refKind)}
                      className="rounded-md border border-zinc-200 bg-white px-2 py-1 font-mono text-xs text-zinc-600 hover:border-amber-400"
                    >
                      {shortSha}
                    </a>
                  )}
                  <span className="text-xs text-zinc-500">{new Date(latestDate).toLocaleDateString(locale === 'ja' ? 'ja-JP' : 'en-US')}</span>
                </div>
              </td>
            </tr>
            {sorted.map((entry) => {
              const isDir = entry.type === 'dir';
              const directForgejoUrl = forgejoTreeUrl(owner, repo, entry.path, branch, refKind);
              const href = directForgejoUrl;
              const downloadUrl = !isDir ? nyankofaceDownloadUrl(owner, repo, entry.path, branch, 'raw', refKind) : null;
              return (
                <tr
                  key={entry.path}
                  className="border-t border-zinc-100 first:border-t-0 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/50"
                >
                  <td className="px-4 py-2.5">
                    <a href={href} className="flex items-center gap-2 text-zinc-800 dark:text-zinc-200" title={ui(locale, 'Forgejoで開く', 'Open in Forgejo')}>
                      <HfIcon name={icon(entry)} className="h-3.5 w-3.5 text-zinc-400" />
                      <span className={isDir ? 'font-medium' : ''}>{entry.name}</span>
                      {!isDir && <span className="rounded border border-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-400">{ui(locale, '安全', 'Safe')}</span>}
                    </a>
                  </td>
                  <td className="hidden px-4 py-2.5 text-xs text-zinc-500 dark:text-zinc-400 md:table-cell">
                    <span className="line-clamp-1">{latestMessage}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-xs text-zinc-500 dark:text-zinc-400">
                    {!isDir ? formatBytes(entry.size) : ''}
                    {downloadUrl && (
                      <DownloadLink href={downloadUrl} className="ml-2 inline-flex h-6 w-6 items-center justify-center rounded border border-zinc-200 hover:border-amber-400" title="Download from NyankoFace">
                        <HfIcon name="download" className="h-3 w-3" />
                      </DownloadLink>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right text-xs text-zinc-500">
                    <a href={directForgejoUrl} className="inline-flex items-center gap-1 hover:text-amber-700" title="Open in Forgejo">
                      <HfIcon name="link" className="h-3 w-3" />
                      Forgejo
                    </a>
                  </td>
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td className="px-4 py-6 text-center text-zinc-500 dark:text-zinc-400" colSpan={4}>
                  {ui(locale, 'このフォルダは空です。', 'This folder is empty.')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        <a href={forgejoUrl} className="inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 font-medium text-zinc-700 hover:border-amber-400">
          <HfIcon name="link" className="h-3.5 w-3.5" />
          {ui(locale, 'このツリーをForgejoで開く', 'Open this tree in Forgejo')}
        </a>
        <code className="rounded-lg bg-zinc-100 px-3 py-2 text-xs text-zinc-600">
          git clone {cloneUrl}
        </code>
      </div>
    </div>
  );
}
