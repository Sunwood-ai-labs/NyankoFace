import { notFound, redirect } from 'next/navigation';
import Link from 'next/link';
import { cache } from 'react';
import {
  getRepo,
  getPagesInspection,
  getContents,
  getCommits,
  getRepoTags,
  searchRepos,
  getTextFile,
  cloneUrl,
  encodeRepositoryPath,
  forgejoRepoUrl,
  forgejoTreeUrl,
  forgejoRawUrl,
  nonTypeTopics,
  repoPromptVersion,
  repoKind,
  repoDefaultBranch,
  ContentEntry,
  RepoKind,
} from '@/lib/forgejo';
import { parseReadme } from '@/lib/markdown';
import MarkdownBody from '@/components/MarkdownBody';
import { timeAgoEn, timeAgoJa } from '@/lib/format';
import { getLocale } from '@/lib/i18n-server';
import { Locale, ui } from '@/lib/i18n';
import DetailTabs from '@/components/DetailTabs';
import CardBadges from '@/components/CardBadges';
import CloneBlock from '@/components/CloneBlock';
import FileTree from '@/components/FileTree';
import SpaceRunner from '@/components/SpaceRunner';
import SpaceStatusBadge from '@/components/SpaceStatusBadge';
import SpaceRuntimeProvider from '@/components/SpaceRuntimeProvider';
import SpaceEnvironmentButton from '@/components/SpaceEnvironmentButton';
import HfIcon, { HfIconName } from '@/components/HfIcon';
import SpaceMetrics from '@/components/SpaceMetrics';
import RepoMetricsPanel from '@/components/RepoMetricsPanel';
import PromptRevisionSwitcher from '@/components/PromptRevisionSwitcher';
import SkillRelationshipMap from '@/components/SkillRelationshipMap';
import CharacterRepositoryPanel from '@/components/CharacterRepositoryPanel';
import { inspectCharacterRepository } from '@/lib/character-format';
import { getAppName } from '@/lib/app-config';
import PagesStatusCard from '@/components/PagesStatusCard';
import { headers } from 'next/headers';
import { requestOriginFromHeaders } from '@/lib/public-origin';
import PipelinePanel from '@/components/PipelinePanel';
import AutomationPreflightPanel from '@/components/AutomationPreflightPanel';
import { inspectPublicAutomationRepository } from '@/lib/automation-repository';
import { buildDisabledAutomationBundle } from '@/lib/automation';
import { ServerTimingTrace } from '@/lib/server-timing';

export const dynamic = 'force-dynamic';
const getCachedRepo = cache(getRepo);

export async function generateMetadata({
  params,
}: {
  params: Promise<{ owner: string; repo: string }>;
}) {
  const { owner, repo } = await params;
  const locale = await getLocale();
  const appName = getAppName();
  const repoInfo = await getCachedRepo(owner, repo);
  const kind = repoInfo ? repoKind(repoInfo.topics) : null;
  const label = kind === 'space' ? 'Space' : kind === 'dataset' ? ui(locale, 'データセット', 'Dataset') : kind === 'skill' ? ui(locale, 'スキル', 'Skill') : kind === 'mcp' ? 'MCP server' : kind === 'prompt' ? ui(locale, 'プロンプト', 'Prompt') : kind === 'doc' ? ui(locale, 'ナレッジ', 'Knowledge') : kind === 'character' ? ui(locale, 'キャラクター', 'Character') : kind === 'benchmark' ? ui(locale, 'ベンチマーク', 'Benchmark') : kind === 'automation' ? 'Automation' : kind === null ? ui(locale, 'リポジトリ', 'Repository') : ui(locale, 'モデル', 'Model');
  const repoName = repoInfo?.full_name || `${owner}/${repo}`;
  return {
    title: `${repoName} - ${label} - ${appName}`,
    description: repoInfo?.description || `${repoName} on ${appName}.`,
  };
}

const KIND_ICON: Record<string, HfIconName> = {
  model: 'model',
  dataset: 'dataset',
  space: 'space',
  skill: 'skill',
  mcp: 'mcp',
  prompt: 'prompt',
  doc: 'doc',
  character: 'character',
  benchmark: 'benchmark',
  automation: 'automation',
};

const MAX_README_PREVIEW_BYTES = 2_000_000;
const MAX_README_SYMLINK_DEPTH = 8;
const REPOSITORY_README_CACHE_TTL_MS = Math.max(
  60,
  Number.parseInt(process.env.README_CACHE_TTL_SECONDS || '300', 10) || 300,
) * 1000;
const MAX_REPOSITORY_README_CACHE_ENTRIES = 64;

type RepositoryReadmeResult =
  | { status: 'present'; raw: string; path: string; size: number }
  | { status: 'absent' | 'unavailable' | 'too-large'; path?: string; size?: number };

const repositoryReadmeCache = new Map<string, { value: RepositoryReadmeResult; expiresAt: number }>();

function pruneRepositoryReadmeCache(now = Date.now(), makeRoom = false): void {
  for (const [key, entry] of repositoryReadmeCache) {
    if (entry.expiresAt <= now) repositoryReadmeCache.delete(key);
  }
  if (!makeRoom) return;
  while (repositoryReadmeCache.size >= MAX_REPOSITORY_README_CACHE_ENTRIES) {
    const oldestKey = repositoryReadmeCache.keys().next().value;
    if (oldestKey === undefined) break;
    repositoryReadmeCache.delete(oldestKey);
  }
}

function normalizeRepositoryPath(value: string): string | undefined {
  if (!value || value.startsWith('/') || value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) {
    return undefined;
  }
  const segments: string[] = [];
  for (const segment of value.split('/')) {
    if (!segment || segment === '.') continue;
    if (segment === '..') {
      if (!segments.length) return undefined;
      segments.pop();
      continue;
    }
    segments.push(segment);
  }
  return segments.join('/') || undefined;
}

function resolveRepositorySymlinkPath(entryPath: string, target: string): string | undefined {
  if (target.startsWith('/')) return undefined;
  const basePath = entryPath.split('/').slice(0, -1).join('/');
  return normalizeRepositoryPath([basePath, target].filter(Boolean).join('/'));
}

async function loadRepositoryReadme(owner: string, repo: string, ref: string): Promise<RepositoryReadmeResult> {
  const cacheKey = `${owner}/${repo}@${ref}`;
  pruneRepositoryReadmeCache();
  const cached = repositoryReadmeCache.get(cacheKey);
  if (cached) {
    repositoryReadmeCache.delete(cacheKey);
    repositoryReadmeCache.set(cacheKey, cached);
    return cached.value;
  }
  const remember = (value: RepositoryReadmeResult): RepositoryReadmeResult => {
    pruneRepositoryReadmeCache(Date.now(), true);
    repositoryReadmeCache.set(cacheKey, { value, expiresAt: Date.now() + REPOSITORY_README_CACHE_TTL_MS });
    return value;
  };

  try {
    const root = await getContents(owner, repo, '', ref);
    if (!root.ok || !Array.isArray(root.data)) return remember({ status: 'unavailable' });

    const readmeEntries = root.data.filter((candidate) =>
      (candidate.type === 'file' || candidate.type === 'symlink') && candidate.name.toLowerCase() === 'readme.md',
    );
    const entry = readmeEntries.find((candidate) => candidate.name === 'README.md') || readmeEntries[0];
    if (!entry) return remember({ status: 'absent' });
    let currentEntry = entry;
    let readmePath = normalizeRepositoryPath(entry.path);
    const visitedReadmePaths = new Set<string>();
    let fileEntry: typeof entry | undefined;
    for (let depth = 0; depth <= MAX_README_SYMLINK_DEPTH; depth += 1) {
      if (!readmePath || visitedReadmePaths.has(readmePath)) {
        return remember({ status: 'unavailable', path: readmePath || entry.path, size: currentEntry.size });
      }
      visitedReadmePaths.add(readmePath);
      if (currentEntry.type === 'file') {
        fileEntry = currentEntry;
        break;
      }
      if (currentEntry.type !== 'symlink' || typeof currentEntry.target !== 'string' || depth === MAX_README_SYMLINK_DEPTH) {
        return remember({ status: 'unavailable', path: readmePath, size: currentEntry.size });
      }
      const targetPath = resolveRepositorySymlinkPath(readmePath, currentEntry.target);
      if (!targetPath) return remember({ status: 'unavailable', path: readmePath, size: currentEntry.size });
      const target = await getContents(owner, repo, targetPath, ref);
      if (!target.ok || !target.data || Array.isArray(target.data)) {
        return remember({ status: 'unavailable', path: targetPath, size: currentEntry.size });
      }
      currentEntry = target.data;
      readmePath = normalizeRepositoryPath(currentEntry.path || targetPath);
    }
    if (!fileEntry || !readmePath) {
      return remember({ status: 'unavailable', path: readmePath || entry.path, size: currentEntry.size });
    }
    if (fileEntry.size >= MAX_README_PREVIEW_BYTES) {
      return remember({ status: 'too-large', path: readmePath, size: fileEntry.size });
    }

    const file = typeof fileEntry.content === 'string'
      ? { ok: true, data: fileEntry }
      : await getContents(owner, repo, readmePath, ref);
    if (!file.ok || !file.data || Array.isArray(file.data) || file.data.type !== 'file' || typeof file.data.content !== 'string') {
      return remember({ status: 'unavailable', path: readmePath, size: fileEntry.size });
    }
    const rawBuffer = Buffer.from(
      file.data.content,
      (file.data.encoding as BufferEncoding) || 'base64',
    );
    const fetchedSize = file.data.size ?? rawBuffer.byteLength;
    if (fetchedSize >= MAX_README_PREVIEW_BYTES || rawBuffer.byteLength >= MAX_README_PREVIEW_BYTES) {
      return remember({ status: 'too-large', path: readmePath, size: fetchedSize });
    }
    return remember({ status: 'present', raw: rawBuffer.toString('utf-8'), path: readmePath, size: fetchedSize });
  } catch {
    return remember({ status: 'unavailable' });
  }
}

export default async function RepoDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ owner: string; repo: string }>;
  searchParams: Promise<{ tab?: string; path?: string; revision?: string; pet?: string }>;
}) {
  const [{ owner, repo }, resolvedSearchParams, requestHeaders] = await Promise.all([params, searchParams, headers()]);
  const requestOrigin = requestOriginFromHeaders(requestHeaders);
  const timing = new ServerTimingTrace();
  const routeStartedAt = performance.now();
  const tab = resolvedSearchParams.tab === 'files'
    ? 'files'
    : resolvedSearchParams.tab === 'pipelines'
      ? 'pipelines'
      : 'card';
  const path = resolvedSearchParams.path || '';

  const [locale, repoInfo] = await Promise.all([
    getLocale(),
    timing.measure('forgejo', () => getCachedRepo(owner, repo)),
  ]);

  if (!repoInfo) {
    // Forgejo may be unreachable, or repo genuinely doesn't exist.
    // Render a graceful empty-state rather than throwing during SSR.
    return (
      <div className="mx-auto max-w-2xl rounded-lg border border-dashed border-zinc-300 p-10 text-center text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
        <p className="mb-2 text-lg font-semibold">{ui(locale, 'リポジトリが見つかりません', 'Repository not found')}</p>
        <p className="text-sm">
          {ui(locale, `${owner}/${repo} は存在しないか、Forgejoに接続できません。`, `${owner}/${repo} does not exist or Forgejo is not reachable.`)}
        </p>
      </div>
    );
  }

  const kind = repoKind(repoInfo.topics);
  const defaultBranch = repoDefaultBranch(repoInfo);
  if (kind === 'space' && tab === 'card' && repoInfo.space_url) {
    redirect(repoInfo.space_url);
  }
  const topicBadges = nonTypeTopics(repoInfo.topics);
  const promptVersion = kind === 'prompt' ? repoPromptVersion(repoInfo.topics) : null;
  const isSpace = kind === 'space';
  const isSpaceApp = isSpace && tab === 'card';
  const [pagesInspection, promptTags, skillCatalog, characterProfile] = await Promise.all([
    isSpaceApp ? Promise.resolve(null) : getPagesInspection(owner, repo),
    kind === 'prompt' ? getRepoTags(owner, repo) : Promise.resolve([]),
    kind === 'skill' ? searchRepos({ topic: 'skill', limit: 100 }) : Promise.resolve(null),
    kind === 'character' ? inspectCharacterRepository(repoInfo) : Promise.resolve(null),
  ]);
  const requestedRevision = resolvedSearchParams.revision?.trim() || null;
  const selectedRevision = requestedRevision && promptTags.some((tag) => tag.name === requestedRevision)
    ? requestedRevision
    : null;
  const kindLabel = isSpace ? 'Spaces' : kind === 'dataset' ? ui(locale, 'データセット', 'Datasets') : kind === 'skill' ? ui(locale, 'スキル', 'Skills') : kind === 'mcp' ? 'MCPs' : kind === 'prompt' ? ui(locale, 'プロンプト', 'Prompts') : kind === 'doc' ? ui(locale, 'ナレッジ', 'Knowledge') : kind === 'character' ? 'Characters' : kind === 'benchmark' ? 'Benchmarks' : kind === 'automation' ? 'Automations' : kind === null ? ui(locale, 'リポジトリ', 'Repository') : ui(locale, 'モデル', 'Models');
  const kindHref = isSpace ? '/spaces' : kind === 'dataset' ? '/datasets' : kind === 'skill' ? '/skills' : kind === 'mcp' ? '/mcps' : kind === 'prompt' ? '/prompts' : kind === 'doc' ? '/docs' : kind === 'character' ? '/characters' : kind === 'benchmark' ? '/benchmarks' : kind === 'automation' ? '/automations' : kind === null ? `/git/${owner}` : '/models';
  const kindIcon = kind ? KIND_ICON[kind] : 'box';
  timing.add('api', performance.now() - routeStartedAt);
  timing.log(`/${owner}/${repo}`);

  const content = (
    <div
      className={isSpaceApp ? 'nyankoface-space-app-page' : ''}
      data-nyankoface-server-timing={timing.serialize()}
    >
      <div className={`nyankoface-repo-header flex min-w-0 flex-wrap items-center gap-4 border-b border-zinc-200 dark:border-zinc-800 ${isSpace ? 'nyankoface-space-header' : ''} ${isSpaceApp ? 'nyankoface-space-app-header mb-0' : 'mb-6 max-sm:block'} ${isSpace && !isSpaceApp ? 'nyankoface-space-detail-header' : ''}`}>
        <div className={isSpace ? 'nyankoface-space-header-main' : 'flex min-w-0 flex-1 items-center gap-2 py-3 max-sm:flex-wrap'}>
          <div className={isSpace ? 'nyankoface-space-header-identity' : 'contents'}>
            <Link
              href={kindHref}
              aria-label={ui(locale, `${kindLabel}へ戻る`, `Back to ${kindLabel}`)}
              title={ui(locale, `${kindLabel}へ戻る`, `Back to ${kindLabel}`)}
              className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              prefetch
            >
              <HfIcon name={kindIcon} className="h-4 w-4" />
            </Link>
            <h1
              className={`flex min-w-0 items-center gap-1 text-lg font-bold ${isSpace ? 'nyankoface-space-header-title' : `max-sm:w-[calc(100%-1.5rem)] ${isSpaceApp ? 'max-sm:flex-nowrap max-sm:text-base' : 'max-sm:flex-wrap'}`}`}
              title={isSpace ? `${owner}/${repoInfo.name}` : undefined}
            >
              <Link
                href={kindHref}
                className={`shrink-0 text-zinc-500 hover:text-zinc-950 hover:underline dark:text-zinc-400 dark:hover:text-zinc-100 ${isSpaceApp ? 'max-sm:hidden' : ''}`}
                prefetch
              >
                {kindLabel}:
              </Link>
              <a href={`/git/${owner}`} className={`text-zinc-500 hover:underline dark:text-zinc-400 ${isSpace ? 'nyankoface-space-header-owner' : ''}`}>{owner}</a>
              <span className="shrink-0 text-zinc-300">/</span>
              <span className={`min-w-0 font-mono text-zinc-950 dark:text-zinc-100 ${isSpace ? 'nyankoface-space-header-repo truncate' : isSpaceApp ? 'truncate' : 'break-words'}`}>{repoInfo.name}</span>
            </h1>
            {isSpace ? (
              <div className="nyankoface-space-header-metrics">
                <SpaceMetrics
                  owner={owner}
                  repo={repo}
                  forgejoHref={forgejoRepoUrl(owner, repo)}
                />
              </div>
            ) : (
              <>
                <a
                  href={forgejoRepoUrl(owner, repo)}
                  title={ui(locale, 'Forgejoでこのプロジェクトにいいねする', 'Open the Forgejo repository to like this project')}
                  className="ml-2 inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-200 px-2.5 text-xs text-zinc-500 hover:bg-zinc-50"
                >
                  <HfIcon name="heart" className="h-3 w-3" />
                  {ui(locale, 'いいね', 'like')}
                </a>
                <a
                  href={forgejoRepoUrl(owner, repo)}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-100 px-2.5 text-xs text-zinc-500 hover:bg-zinc-50"
                  title={repoInfo.stars_count == null ? ui(locale, 'スター数は未集計です', 'Star count is unavailable') : ui(locale, `Forgejoスター ${repoInfo.stars_count}件`, `${repoInfo.stars_count} Forgejo stars`)}
                  data-metric-state={repoInfo.stars_count == null ? 'unavailable' : 'available'}
                >
                  <HfIcon name="star" className="h-3 w-3" />
                  {repoInfo.stars_count ?? '—'}
                </a>
              </>
            )}
          </div>
          {isSpace ? (
            <div className="nyankoface-space-header-controls">
              <SpaceStatusBadge owner={owner} repo={repo} variant="header" />
              <SpaceEnvironmentButton owner={owner} repo={repo} />
            </div>
          ) : null}
        </div>
        <div className={`min-w-0 ${isSpaceApp ? 'max-sm:hidden' : ''}`}>
          <DetailTabs owner={owner} repo={repo} active={tab} isSpace={isSpace} kind={kind} communityCount={repoInfo.open_issues_count} revision={selectedRevision} locale={locale} />
        </div>
      </div>

      {!isSpace && (
        <div className="mb-6">
          {repoInfo.description && (
            <p className="text-zinc-600 dark:text-zinc-400">{repoInfo.description}</p>
          )}
          {promptVersion ? (
            <a href={`${kindHref}?q=${encodeURIComponent(`version-${promptVersion}`)}`} className="mt-3 inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-3 py-1 font-mono text-xs font-bold text-orange-800 hover:bg-orange-100">
              <HfIcon name="prompt" className="h-3 w-3" /> {ui(locale, '現在のリリース', 'Current release')} {promptVersion}
            </a>
          ) : null}
          {kind === 'prompt' && promptTags.length > 0 ? (
            <PromptRevisionSwitcher owner={owner} repo={repo} tags={promptTags} selectedRevision={selectedRevision} locale={locale} />
          ) : null}
          {topicBadges.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {topicBadges.map((t) => (
                <a
                  key={t}
                  href={`${kindHref}?q=${encodeURIComponent(t)}`}
                  className="rounded-md bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:bg-zinc-800 dark:text-zinc-300"
                >
                  {t}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      <RepoMetricsPanel owner={owner} repo={repo} recordView />

      {isSpaceApp && (
        <div className="nyankoface-space-app-runner">
          <SpaceRunner owner={owner} repo={repo} description={repoInfo.description} />
        </div>
      )}

      {!isSpaceApp && <div className={tab === 'files' || tab === 'pipelines' ? '' : 'grid min-w-0 grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_280px]'}>
        <div className="min-w-0">
          {tab === 'card' ? (
            <CardTabContent
              owner={owner}
              repo={repo}
              kind={kind}
              defaultBranch={defaultBranch}
              revision={selectedRevision}
              skillRepo={kind === 'skill' ? repoInfo : null}
              skillCatalog={skillCatalog?.data || []}
              characterProfile={characterProfile}
              locale={locale}
            />
          ) : tab === 'pipelines' ? (
            <PipelinePanel
              owner={owner}
              repo={repo}
              defaultBranch={defaultBranch}
              locale={locale}
            />
          ) : (
            <FilesTabContent
              owner={owner}
              repo={repo}
              path={path}
              defaultBranch={defaultBranch}
              revision={selectedRevision}
              updatedAt={repoInfo.updated_at}
              requestOrigin={requestOrigin}
              locale={locale}
            />
          )}
        </div>

        {tab === 'card' && <aside className="flex flex-col gap-4">
          {kind === 'skill' ? (
            <div className="hidden lg:block">
              <SkillRelationshipMap repo={repoInfo} catalog={skillCatalog?.data || []} placement="sidebar" locale={locale} />
            </div>
          ) : null}
          <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              {isSpace ? ui(locale, 'Spaceの操作', 'Space actions') : kind === 'dataset' ? ui(locale, 'データセットの操作', 'Dataset actions') : kind === 'skill' ? ui(locale, 'スキルの操作', 'Skill actions') : kind === 'mcp' ? ui(locale, 'MCPの操作', 'MCP actions') : kind === 'prompt' ? ui(locale, 'プロンプトの操作', 'Prompt actions') : kind === 'doc' ? ui(locale, 'ナレッジの操作', 'Knowledge actions') : kind === 'character' ? ui(locale, 'キャラクターの操作', 'Character actions') : kind === 'benchmark' ? ui(locale, 'ベンチマークの操作', 'Benchmark actions') : kind === 'automation' ? ui(locale, 'Automationの操作', 'Automation actions') : kind === null ? ui(locale, 'リポジトリの操作', 'Repository actions') : ui(locale, 'モデルの操作', 'Model actions')}
            </p>
            <div className="grid gap-2">
              {isSpace ? (
                <>
                  <a href={`/${owner}/${repo}`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-semibold text-white hover:bg-zinc-800">
                    <HfIcon name="play" className="h-3.5 w-3.5" />
                    {ui(locale, 'アプリを開く', 'Open app')}
                  </a>
                  <a href={`/new?type=space&template=${encodeURIComponent(`${owner}/${repo}`)}`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="fork" className="h-3.5 w-3.5" />
                    {ui(locale, 'Spaceを複製', 'Duplicate Space')}
                  </a>
                </>
              ) : kind === 'dataset' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-semibold text-white hover:bg-zinc-800">
                    <HfIcon name="table" className="h-3.5 w-3.5" />
                    {ui(locale, 'データセットをプレビュー', 'Preview dataset')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="download" className="h-3.5 w-3.5" />
                    {ui(locale, 'このデータセットを使う', 'Use this dataset')}
                  </a>
                </>
              ) : kind === 'skill' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-violet-700 px-3 text-sm font-semibold text-white hover:bg-violet-800">
                    <HfIcon name="skill" className="h-3.5 w-3.5" />
                    {ui(locale, 'SKILL.mdを確認', 'Inspect SKILL.md')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="download" className="h-3.5 w-3.5" />
                    {ui(locale, 'このスキルを導入', 'Install this skill')}
                  </a>
                </>
              ) : kind === 'mcp' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-700 px-3 text-sm font-semibold text-white hover:bg-cyan-800">
                    <HfIcon name="mcp" className="h-3.5 w-3.5" />
                    {ui(locale, 'サーバーを確認', 'Inspect server')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="code" className="h-3.5 w-3.5" />
                    {ui(locale, 'MCPを設定', 'Configure MCP')}
                  </a>
                </>
              ) : kind === 'prompt' ? (
                <>
                  <a href={selectedRevision ? forgejoTreeUrl(owner, repo, '', selectedRevision, 'tag') : `/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-orange-700 px-3 text-sm font-semibold text-white hover:bg-orange-800">
                    <HfIcon name="prompt" className="h-3.5 w-3.5" />
                    {ui(locale, 'プロンプト原文を確認', 'Inspect prompt source')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="fork" className="h-3.5 w-3.5" />
                    {ui(locale, 'このプロンプトをフォーク', 'Fork this prompt')}
                  </a>
                </>
              ) : kind === 'doc' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-teal-800 px-3 text-sm font-semibold text-white hover:bg-teal-900">
                    <HfIcon name="doc" className="h-3.5 w-3.5" />
                    {ui(locale, 'ソースを見る', 'Browse source')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="filePen" className="h-3.5 w-3.5" />
                    {ui(locale, 'このナレッジを編集', 'Edit this knowledge')}
                  </a>
                </>
              ) : kind === 'character' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-fuchsia-700 px-3 text-sm font-semibold text-white hover:bg-fuchsia-800">
                    <HfIcon name="character" className="h-3.5 w-3.5" />
                    {ui(locale, 'アセットを確認', 'Inspect assets')}
                  </a>
                  <a href={`/new?type=character&template=${encodeURIComponent(`${owner}/${repo}`)}`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="fork" className="h-3.5 w-3.5" />
                    {ui(locale, 'キャラクターを複製', 'Duplicate character')}
                  </a>
                </>
              ) : kind === 'benchmark' ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-sky-700 px-3 text-sm font-semibold text-white hover:bg-sky-800">
                    <HfIcon name="benchmark" className="h-3.5 w-3.5" />
                    {ui(locale, '評価コードを見る', 'Browse evaluation code')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="fork" className="h-3.5 w-3.5" />
                    {ui(locale, 'Forgejoで管理', 'Manage in Forgejo')}
                  </a>
                </>
              ) : kind === 'automation' ? (
                <>
                  <a href="#automation-preflight" className="nyankoface-automation-primary inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-amber-950 px-3 text-sm font-semibold text-white hover:bg-amber-900 dark:bg-amber-300 dark:text-amber-950">
                    <HfIcon name="automation" className="h-3.5 w-3.5" />
                    {ui(locale, '実行前チェック', 'Review preflight')}
                  </a>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="file" className="h-3.5 w-3.5" />
                    {ui(locale, '構成ファイルを見る', 'Browse package files')}
                  </a>
                </>
              ) : kind === null ? (
                <>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-semibold text-white hover:bg-zinc-800">
                    <HfIcon name="folder" className="h-3.5 w-3.5" />
                    {ui(locale, 'ファイルを見る', 'Browse files')}
                  </a>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="link" className="h-3.5 w-3.5" />
                    {ui(locale, 'リポジトリを開く', 'Open repository')}
                  </a>
                </>
              ) : (
                <>
                  <a href={forgejoRepoUrl(owner, repo)} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-semibold text-white hover:bg-zinc-800">
                    <HfIcon name="play" className="h-3.5 w-3.5" />
                    {ui(locale, 'このモデルを使う', 'Use this model')}
                  </a>
                  <a href={`/${owner}/${repo}?tab=files`} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
                    <HfIcon name="code" className="h-3.5 w-3.5" />
                    {ui(locale, 'デプロイ', 'Deploy')}
                  </a>
                </>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <CloneBlock cloneUrl={cloneUrl(owner, repo, requestOrigin)} />
          </div>

          {pagesInspection ? <PagesStatusCard inspection={pagesInspection} publicOrigin={requestOrigin} /> : null}

          <div className="rounded-lg border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              {ui(locale, '統計', 'Stats')}
            </p>
            <ul className="space-y-2 text-zinc-600 dark:text-zinc-400">
              <li>
                <a
                  href={forgejoRepoUrl(owner, repo)}
                  className="flex items-center gap-2 hover:text-zinc-900"
                  title={repoInfo.stars_count == null ? ui(locale, 'スター数は未集計です', 'Star count is unavailable') : undefined}
                  data-metric-state={repoInfo.stars_count == null ? 'unavailable' : 'available'}
                >
                  <HfIcon name="star" className="h-3.5 w-3.5 text-zinc-400" />
                  {ui(locale, 'スター', 'Stars')}: {repoInfo.stars_count ?? '—'}
                </a>
              </li>
              <li>
                <a
                  href={`/git/${owner}/${repo}/forks`}
                  className="flex items-center gap-2 hover:text-zinc-900"
                  title={repoInfo.forks_count == null ? ui(locale, 'フォーク数は未集計です', 'Fork count is unavailable') : undefined}
                  data-metric-state={repoInfo.forks_count == null ? 'unavailable' : 'available'}
                >
                  <HfIcon name="fork" className="h-3.5 w-3.5 text-zinc-400" />
                  {ui(locale, 'フォーク', 'Forks')}: {repoInfo.forks_count ?? '—'}
                </a>
              </li>
              <li><a href={forgejoRepoUrl(owner, repo)} className="flex items-center gap-2 hover:text-zinc-900"><HfIcon name="eye" className="h-3.5 w-3.5 text-zinc-400" />Watchers: {repoInfo.watchers_count ?? 0}</a></li>
              <li className="flex items-center gap-2" title={repoInfo.updated_at}>
                <HfIcon name="clock" className="h-3.5 w-3.5 text-zinc-400" />{ui(locale, `更新 ${timeAgoJa(repoInfo.updated_at)}`, `Updated ${timeAgoEn(repoInfo.updated_at)}`)}
              </li>
            </ul>
          </div>

          <a
            href={forgejoRepoUrl(owner, repo)}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-white p-4 text-center text-sm font-semibold text-zinc-700 hover:border-amber-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
          >
            <HfIcon name="link" className="h-3.5 w-3.5" />
            {ui(locale, 'Forgejoで開く', 'Open in Forgejo')}
          </a>
        </aside>}
      </div>}
    </div>
  );
  return isSpace ? (
    <SpaceRuntimeProvider key={`${owner}/${repo}`} owner={owner} repo={repo}>{content}</SpaceRuntimeProvider>
  ) : content;
}

async function CardTabContent({
  owner,
  repo,
  kind,
  defaultBranch,
  revision,
  skillRepo,
  skillCatalog,
  characterProfile,
  locale,
}: {
  owner: string;
  repo: string;
  kind: RepoKind | null;
  defaultBranch: string;
  revision?: string | null;
  skillRepo: import('@/lib/forgejo').Repo | null;
  skillCatalog: import('@/lib/forgejo').Repo[];
  characterProfile: import('@/lib/character-format').CharacterRepositoryProfile | null;
  locale: Locale;
}) {
  const ref = revision || defaultBranch;
  const refKind = revision ? 'tag' : 'branch';
  const [readme, taggedPromptRaw] = await Promise.all([
    loadRepositoryReadme(owner, repo, ref),
    kind === 'prompt' && revision ? getTextFile(owner, repo, 'PROMPT.md', revision) : Promise.resolve(null),
  ]);
  const automationInspection = kind === 'automation'
    ? await inspectPublicAutomationRepository(owner, repo, ref)
    : null;
  const reviewedAutomationToml = automationInspection?.preflight.ok
    ? buildDisabledAutomationBundle(automationInspection.preflight, { acknowledgeWarnings: true })
    : null;
  const renderedRaw = taggedPromptRaw || (readme.status === 'present' ? readme.raw : null);
  const readmeDirectory = !taggedPromptRaw && readme.status === 'present'
    ? readme.path.split('/').slice(0, -1).join('/')
    : '';
  const readmeAssetPath = readmeDirectory ? `${readmeDirectory}/` : '';
  const readmeUrlAssetPath = encodeRepositoryPath(readmeAssetPath);
  let readmeStatus: RepositoryReadmeResult['status'] | 'empty' | 'parse' = taggedPromptRaw ? 'present' : readme.status;
  let frontmatter: import('@/lib/markdown').ModelCardFrontmatter = {};
  let bodyHtml = '';
  if (renderedRaw) {
    try {
      const parsed = parseReadme(renderedRaw, {
        assetBaseUrl: forgejoRawUrl(owner, repo, readmeAssetPath, ref, refKind),
        relativeLinkBaseUrl: revision
          ? forgejoTreeUrl(owner, repo, readmeDirectory, revision, 'tag') + '/'
          : `/${owner}/${repo}/blob/${readmeUrlAssetPath}`,
        locale,
      });
      frontmatter = parsed.frontmatter;
      bodyHtml = parsed.bodyHtml;
      if (!bodyHtml.trim()) readmeStatus = 'empty';
    } catch {
      readmeStatus = 'parse';
    }
  } else if (readmeStatus === 'present') {
    readmeStatus = 'empty';
  }

  const readmeMessage = readmeStatus === 'absent'
    ? ui(locale, 'README.mdがありません。ファイル一覧からリポジトリの内容を確認できます。', 'No README.md was found. Browse the repository files to inspect its contents.')
    : readmeStatus === 'too-large'
      ? ui(locale, 'README.mdが大きすぎるためプレビューできません。ファイル一覧から原文を開けます。', 'README.md is too large to preview. Open the raw file from the repository files.')
      : readmeStatus === 'parse'
        ? ui(locale, 'README.mdをMarkdownとして解析できませんでした。ファイル一覧から原文を確認できます。', 'README.md could not be parsed as Markdown. Open the raw file from the repository files.')
        : readmeStatus === 'empty'
          ? ui(locale, 'README.mdは空か、表示できるMarkdown本文がありません。', 'README.md is empty or has no renderable Markdown body.')
          : ui(locale, 'README.mdを取得できませんでした。権限またはForgejoの接続状態を確認してください。', 'README.md could not be loaded. Check repository access or Forgejo availability.');

  return (
    <div>
      {automationInspection ? (
        <div id="automation-preflight">
          <AutomationPreflightPanel
            owner={owner}
            repo={repo}
            preflight={automationInspection.preflight}
            reviewedToml={reviewedAutomationToml}
          />
        </div>
      ) : null}
      {kind === 'character' && characterProfile ? (
        <CharacterRepositoryPanel owner={owner} repo={repo} branch={defaultBranch} profile={characterProfile} locale={locale} />
      ) : null}
      {kind === 'prompt' && revision ? (
        <div className="mb-5 flex items-center gap-3 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-900 dark:border-orange-950 dark:bg-orange-950/20 dark:text-orange-200">
          <HfIcon name="prompt" className="h-4 w-4 shrink-0" />
          <span>{ui(locale, <><strong className="font-mono">{revision}</strong> のGit tagに保存された <code>PROMPT.md</code> 原文を表示しています。</>, <>Showing the original <code>PROMPT.md</code> stored in Git tag <strong className="font-mono">{revision}</strong>.</>)}</span>
        </div>
      ) : null}
      {kind ? <CardBadges frontmatter={frontmatter} basePath={kind === 'dataset' ? '/datasets' : kind === 'space' ? '/spaces' : kind === 'skill' ? '/skills' : kind === 'mcp' ? '/mcps' : kind === 'prompt' ? '/prompts' : kind === 'doc' ? '/docs' : kind === 'character' ? '/characters' : kind === 'benchmark' ? '/benchmarks' : kind === 'automation' ? '/automations' : '/models'} /> : null}
      {kind === 'skill' && skillRepo ? (
        <div className="mb-7 lg:hidden">
          <SkillRelationshipMap repo={skillRepo} catalog={skillCatalog} placement="mobile" locale={locale} />
        </div>
      ) : null}
      {readmeStatus !== 'present' ? (
        <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
          <p>{readmeMessage}</p>
          {kind === 'skill' ? <p className="mt-2">{ui(locale, 'スキル連携情報は', 'Skill relationships remain available from')} <code>skill.json</code>{ui(locale, 'で確認できます。', '.')}</p> : null}
          <a
            href={revision ? `/${owner}/${repo}?tab=files&revision=${encodeURIComponent(revision)}` : `/${owner}/${repo}?tab=files`}
            className="mt-3 inline-block text-accent-dark hover:underline"
          >
            {ui(locale, 'ファイル一覧を開く', 'Browse repository files')}
          </a>
        </div>
      ) : (
        <MarkdownBody
          className={kind === 'skill' || kind === 'prompt' || kind === 'doc'
            ? 'github-markdown-body prose-nyankoface min-w-0 bg-white dark:bg-zinc-900'
            : 'prose-nyankoface min-w-0 rounded-lg border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900'}
          html={bodyHtml}
        />
      )}
    </div>
  );
}

async function FilesTabContent({
  owner,
  repo,
  path,
  defaultBranch,
  revision,
  updatedAt,
  requestOrigin,
  locale,
}: {
  owner: string;
  repo: string;
  path: string;
  defaultBranch: string;
  revision?: string | null;
  updatedAt: string;
  requestOrigin?: string;
  locale: Locale;
}) {
  const ref = revision || defaultBranch;
  const refKind = revision ? 'tag' as const : 'branch' as const;
  const [res, commits] = await Promise.all([
    getContents(owner, repo, path, ref),
    getCommits(owner, repo, path, 8, ref),
  ]);

  if (!res.ok || !res.data) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 p-8 text-center text-sm text-zinc-500 dark:border-zinc-700 dark:text-zinc-400">
        {ui(locale, 'ファイルを読み込めませんでした。', 'Could not load files.')}
      </div>
    );
  }

  const entries: ContentEntry[] = Array.isArray(res.data) ? res.data : [res.data];

  return (
    <FileTree
      owner={owner}
      repo={repo}
      currentPath={path}
      entries={entries}
      branch={ref}
      commits={commits}
      updatedAt={updatedAt}
      forgejoUrl={forgejoTreeUrl(owner, repo, path, ref, refKind)}
      cloneUrl={cloneUrl(owner, repo, requestOrigin)}
      refKind={refKind}
      revision={revision}
      locale={locale}
    />
  );
}
