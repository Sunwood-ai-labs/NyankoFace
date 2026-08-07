import Link from 'next/link';
import { notFound } from 'next/navigation';
import {
  forgejoCommitsUrl,
  forgejoRawUrl,
  forgejoTreeUrl,
  getContents,
  getRawFile,
  getRepo,
  isLfsPointer,
  nyankofaceDownloadUrl,
} from '@/lib/forgejo';
import { parseReadme } from '@/lib/markdown';
import { formatBytes } from '@/lib/format';
import HfIcon from '@/components/HfIcon';
import DownloadLink from '@/components/DownloadLink';
import MarkdownBody from '@/components/MarkdownBody';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';

export const dynamic = 'force-dynamic';

const TEXT_EXTENSIONS = new Set([
  'md', 'txt', 'json', 'yaml', 'yml', 'toml', 'py', 'js', 'ts', 'tsx', 'jsx',
  'css', 'html', 'sh', 'cfg', 'ini', 'gitattributes', 'gitignore', 'csv', 'tsv',
  'dockerfile', 'requirements', 'lock', 'cfg',
]);
const MAX_TEXT_PREVIEW_BYTES = 2_000_000;

type ReadmePreviewFailure = 'empty' | 'unavailable' | 'too-large' | 'parse';

function isProbablyText(name: string): boolean {
  const lower = name.toLowerCase();
  const ext = lower.split('.').pop() || '';
  if (lower === 'dockerfile' || lower === 'requirements.txt') return true;
  return TEXT_EXTENSIONS.has(ext);
}

function isReadmePath(path: string): boolean {
  return path.split('/').pop()?.toLowerCase() === 'readme.md';
}

function directoryUrl(url: string): string {
  return url.endsWith('/') ? url : `${url}/`;
}

export default async function FileViewPage({
  params,
}: {
  params: Promise<{ owner: string; repo: string; path: string[] }>;
}) {
  const { owner, repo, path: pathSegments } = await params;
  const locale = await getLocale();
  const path = pathSegments.map(decodeURIComponent).join('/');
  const repoInfo = await getRepo(owner, repo);
  const branch = repoInfo?.default_branch || 'main';

  const contentsRes = await getContents(owner, repo, path, branch);
  if (!contentsRes.ok || !contentsRes.data || Array.isArray(contentsRes.data)) {
    notFound();
  }
  const entry = contentsRes.data;

  const rawUrl = forgejoRawUrl(owner, repo, path, branch);
  const forgejoFileUrl = forgejoTreeUrl(owner, repo, path, branch);
  const historyUrl = forgejoCommitsUrl(owner, repo, path, branch);

  let textContent: string | null = null;
  let lfs = false;
  const isReadme = entry.type === 'file' && isReadmePath(path);
  let readmeHtml: string | null = null;
  let readmeFailure: ReadmePreviewFailure | null = null;

  if (isProbablyText(entry.name) && entry.size < MAX_TEXT_PREVIEW_BYTES) {
    textContent = await getRawFile(owner, repo, path, branch);
    if (textContent && isLfsPointer(textContent)) {
      lfs = true;
    }
  }
  const downloadUrl = nyankofaceDownloadUrl(owner, repo, path, branch, lfs ? 'lfs' : 'raw');

  const dirPath = path.split('/').slice(0, -1).join('/');
  if (isReadme && !lfs) {
    if (entry.size >= MAX_TEXT_PREVIEW_BYTES) {
      readmeFailure = 'too-large';
    } else if (textContent === null) {
      readmeFailure = 'unavailable';
    } else if (!textContent.trim()) {
      readmeFailure = 'empty';
    } else {
      try {
        const parsed = parseReadme(textContent, {
          assetBaseUrl: forgejoRawUrl(owner, repo, dirPath ? `${dirPath}/` : '', branch),
          relativeLinkBaseUrl: directoryUrl(forgejoTreeUrl(owner, repo, dirPath, branch)),
          locale,
        });
        if (parsed.bodyHtml.trim()) {
          readmeHtml = parsed.bodyHtml;
        } else {
          readmeFailure = 'empty';
        }
      } catch {
        readmeFailure = 'parse';
      }
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
        <Link
          href={forgejoTreeUrl(owner, repo, dirPath, branch)}
          className="inline-flex items-center gap-1.5 hover:text-accent-dark hover:underline"
        >
          <HfIcon name="arrowLeft" className="h-3 w-3" />
          {ui(locale, 'ファイル一覧へ戻る', 'Back to files')}
        </Link>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm">{path}</span>
          {lfs && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
              LFS
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
          <span>{formatBytes(entry.size)}</span>
          <a href={rawUrl} className="inline-flex items-center gap-1 rounded-lg border border-zinc-300 px-3 py-1.5 font-medium hover:border-accent dark:border-zinc-700">
            <HfIcon name="file" className="h-3 w-3" />
            {ui(locale, '原文', 'Raw')}
          </a>
          <DownloadLink href={downloadUrl} download className="inline-flex items-center gap-1 rounded-lg border border-zinc-300 px-3 py-1.5 font-medium hover:border-accent dark:border-zinc-700">
            <HfIcon name="download" className="h-3 w-3" />
            {ui(locale, 'ダウンロード', 'Download')}
          </DownloadLink>
          <a href={historyUrl} className="inline-flex items-center gap-1 rounded-lg border border-zinc-300 px-3 py-1.5 font-medium hover:border-accent dark:border-zinc-700">
            <HfIcon name="clock" className="h-3 w-3" />
            {ui(locale, '履歴', 'History')}
          </a>
          <a href={forgejoFileUrl} className="inline-flex items-center gap-1 rounded-lg border border-zinc-300 px-3 py-1.5 font-medium hover:border-accent dark:border-zinc-700">
            <HfIcon name="link" className="h-3 w-3" />
            Forgejo
          </a>
        </div>
      </div>

      {lfs ? (
        <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50 p-6 text-center dark:border-amber-800 dark:bg-amber-900/20">
          <p className="mb-3 text-sm text-zinc-700 dark:text-zinc-300">
            {ui(locale, 'このファイルはGit LFSで保存されています。ポインターではなく実体ファイルをダウンロードしてください。', 'This file is stored with Git LFS. Download the resolved file instead of the pointer.')}
          </p>
          <DownloadLink
            href={downloadUrl}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-950"
          >
            <HfIcon name="download" className="h-3.5 w-3.5" />
            {ui(locale, 'LFSファイルをダウンロード', 'Download LFS file')}
          </DownloadLink>
        </div>
      ) : readmeHtml !== null ? (
        <MarkdownBody
          className="github-markdown-body prose-nyankoface min-w-0 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900"
          html={readmeHtml}
        />
      ) : readmeFailure ? (
        <div>
          <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
            {readmeFailure === 'empty'
              ? ui(locale, 'README.mdは空か、表示できるMarkdown本文がありません。', 'README.md is empty or has no renderable Markdown body.')
              : readmeFailure === 'unavailable'
                ? ui(locale, 'README.mdを取得できませんでした。権限またはForgejoの状態を確認してください。', 'README.md could not be loaded. Check repository access or Forgejo availability.')
                : readmeFailure === 'too-large'
                  ? ui(locale, 'README.mdが大きすぎるためプレビューできません。', 'README.md is too large to preview.')
                  : ui(locale, 'README.mdをMarkdownとして解析できませんでした。原文を表示しています。', 'README.md could not be parsed as Markdown. Showing the source instead.')}
            <br />
            <a href={rawUrl} className="mt-2 inline-block text-accent-dark hover:underline">
              {ui(locale, '原文ファイルを開く', 'Open raw file')}
            </a>
          </div>
          {readmeFailure === 'parse' && textContent !== null ? (
            <pre className="mt-4 overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 text-xs leading-relaxed text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
              <code>{textContent}</code>
            </pre>
          ) : null}
        </div>
      ) : textContent !== null ? (
        <pre className="overflow-x-auto rounded-lg border border-zinc-200 bg-white p-4 text-xs leading-relaxed text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
          <code>{textContent}</code>
        </pre>
      ) : (
        <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
          {ui(locale, 'このファイルはプレビューできません。', 'This file cannot be previewed.')}
          <br />
          <a href={rawUrl} className="mt-2 inline-block text-accent-dark hover:underline">
            {ui(locale, '原文ファイルを開く', 'Open raw file')}
          </a>
        </div>
      )}
    </div>
  );
}
