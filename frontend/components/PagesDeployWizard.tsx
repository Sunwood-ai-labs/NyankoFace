'use client';

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';
import { shareablePublicUrl } from '@/lib/public-origin';
import type { PagesInspection } from '@/lib/forgejo';

type PagesMethod = 'gh-pages' | 'docs' | 'vitepress';

interface DeployCommit {
  sha: string;
  branch: string;
  path: string;
  message: string;
}

interface DeployResult {
  owner: string;
  repo: string;
  method: PagesMethod;
  status: 'published' | 'queued' | 'failed';
  public_url: string;
  actions_url: string;
  commits: DeployCommit[];
  logs: string[];
  inspection: PagesInspection;
}

const methods: Array<{
  id: PagesMethod;
  titleJa: string;
  title: string;
  descriptionJa: string;
  description: string;
  files: string[];
}> = [
  {
    id: 'gh-pages',
    titleJa: '静的HTMLをすぐ公開',
    title: 'Publish static HTML now',
    descriptionJa: 'gh-pages branchを作成し、ルートのindex.htmlを公開します。',
    description: 'Create a gh-pages branch and publish a root index.html.',
    files: ['gh-pages/index.html'],
  },
  {
    id: 'docs',
    titleJa: 'default branchのdocs/から公開',
    title: 'Publish from docs/',
    descriptionJa: '既定branchにdocs/index.htmlを追加します。小さな手書きサイト向けです。',
    description: 'Add docs/index.html on the default branch for a small checked-in site.',
    files: ['DEFAULT_BRANCH/docs/index.html'],
  },
  {
    id: 'vitepress',
    titleJa: 'VitePress + Forgejo Actions',
    title: 'VitePress + Forgejo Actions',
    descriptionJa: 'build用sourceとworkflowを追加し、Actionsからgh-pagesへ公開します。',
    description: 'Add build source and a workflow that publishes the output to gh-pages.',
    files: [
      'DEFAULT_BRANCH/package.json',
      'DEFAULT_BRANCH/docs/index.md',
      'DEFAULT_BRANCH/docs/.vitepress/config.mts',
      'DEFAULT_BRANCH/.forgejo/workflows/publish-pages.yml',
    ],
  },
];

function safeSegment(value: string): boolean {
  return /^[A-Za-z0-9._-]+$/.test(value);
}

export default function PagesDeployWizard({
  initialOwner = '',
  initialRepo = '',
  publicOrigin,
}: {
  initialOwner?: string;
  initialRepo?: string;
  publicOrigin?: string;
}) {
  const { locale } = useLocale();
  const [owner, setOwner] = useState(initialOwner);
  const [repo, setRepo] = useState(initialRepo);
  const [method, setMethod] = useState<PagesMethod>('gh-pages');
  const [confirmed, setConfirmed] = useState(false);
  const [inspection, setInspection] = useState<PagesInspection | null>(null);
  const [checking, setChecking] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<DeployResult | null>(null);
  const didInitialInspect = useRef(false);
  const validTarget = safeSegment(owner) && safeSegment(repo);
  const selectedMethod = useMemo(
    () => methods.find((item) => item.id === method) || methods[0],
    [method],
  );

  const inspect = useCallback(async () => {
    if (!safeSegment(owner) || !safeSegment(repo)) {
      setError(ui(locale, '所有者とリポジトリ名を入力してください。', 'Enter an owner and repository name.'));
      return;
    }
    setChecking(true);
    setError('');
    try {
      const response = await fetch(
        `/api/pages/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/status`,
        { cache: 'no-store' },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || payload.error || 'Inspection failed.');
      setInspection(payload as PagesInspection);
    } catch (cause) {
      setInspection(null);
      setError(cause instanceof Error ? cause.message : 'Inspection failed.');
    } finally {
      setChecking(false);
    }
  }, [locale, owner, repo]);

  useEffect(() => {
    if (didInitialInspect.current || !initialOwner || !initialRepo) return;
    didInitialInspect.current = true;
    void inspect();
  }, [initialOwner, initialRepo, inspect]);

  async function deploy(event: FormEvent) {
    event.preventDefault();
    if (!validTarget || !confirmed || deploying) return;
    setDeploying(true);
    setError('');
    setResult(null);
    try {
      const response = await fetch(
        `/api/pages/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/deploy`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ method, confirmed: true }),
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || ui(locale, 'デプロイに失敗しました。', 'Deployment failed.'));
      }
      setResult(payload as DeployResult);
      setInspection((payload as DeployResult).inspection);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : ui(locale, 'デプロイに失敗しました。', 'Deployment failed.'));
    } finally {
      setDeploying(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
      <form
        onSubmit={deploy}
        data-navigation-feedback="off"
        className="space-y-6 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 sm:p-7"
      >
        <section>
          <p className="nyankoface-pages-step-heading text-xs font-bold uppercase tracking-[0.16em] text-indigo-600 dark:text-indigo-300">
            1 · {ui(locale, '公開リポジトリを選ぶ', 'Choose a public repository')}
          </p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-zinc-800 dark:text-zinc-200">{ui(locale, '所有者', 'Owner')}</span>
              <input
                value={owner}
                onChange={(event) => {
                  setOwner(event.target.value.trim());
                  setInspection(null);
                  setResult(null);
                  setConfirmed(false);
                }}
                placeholder="nyankoface"
                className="h-11 w-full rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-950 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-zinc-700 dark:bg-zinc-950 dark:text-white dark:focus:ring-indigo-950"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-semibold text-zinc-800 dark:text-zinc-200">{ui(locale, 'リポジトリ', 'Repository')}</span>
              <input
                value={repo}
                onChange={(event) => {
                  setRepo(event.target.value.trim());
                  setInspection(null);
                  setResult(null);
                  setConfirmed(false);
                }}
                placeholder="my-pages-site"
                className="h-11 w-full rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-950 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-zinc-700 dark:bg-zinc-950 dark:text-white dark:focus:ring-indigo-950"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={() => void inspect()}
            disabled={!validTarget || checking}
            className="mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            <HfIcon name={checking ? 'spinner' : 'search'} className={`h-3.5 w-3.5 ${checking ? 'animate-spin' : ''}`} />
            {checking ? ui(locale, '確認中…', 'Checking…') : ui(locale, '公開条件を確認', 'Check publishing conditions')}
          </button>
        </section>

        <section>
          <p className="nyankoface-pages-step-heading text-xs font-bold uppercase tracking-[0.16em] text-indigo-600 dark:text-indigo-300">
            2 · {ui(locale, '公開方式を選ぶ', 'Choose a publishing method')}
          </p>
          <div className="mt-3 grid gap-3">
            {methods.map((item) => (
              <label
                key={item.id}
                className={`nyankoface-pages-method cursor-pointer rounded-xl border p-4 transition ${
                  method === item.id
                    ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200 dark:border-indigo-600 dark:bg-indigo-950/35 dark:ring-indigo-900'
                    : 'border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600'
                }`}
                data-selected={method === item.id ? 'true' : 'false'}
              >
                <span className="flex items-start gap-3">
                  <input
                    type="radio"
                    name="pages-method"
                    value={item.id}
                    checked={method === item.id}
                    onChange={() => {
                      setMethod(item.id);
                      setConfirmed(false);
                      setResult(null);
                    }}
                    className="mt-1 h-4 w-4 accent-indigo-700"
                  />
                  <span>
                    <span className="nyankoface-pages-method-title block text-sm font-bold text-zinc-950 dark:text-white">{ui(locale, item.titleJa, item.title)}</span>
                    <span className="nyankoface-pages-method-description mt-1 block text-xs leading-5 text-zinc-600 dark:text-zinc-300">{ui(locale, item.descriptionJa, item.description)}</span>
                  </span>
                </span>
              </label>
            ))}
          </div>
        </section>

        <section>
          <p className="nyankoface-pages-step-heading text-xs font-bold uppercase tracking-[0.16em] text-indigo-600 dark:text-indigo-300">
            3 · {ui(locale, '変更内容を確認する', 'Review repository changes')}
          </p>
          <div className="nyankoface-pages-diff mt-3 rounded-xl bg-zinc-950 p-4 font-mono text-xs text-zinc-200 dark:bg-black">
            {selectedMethod.files.map((path) => (
              <p key={path} className="flex items-start gap-2 py-1">
                <span className="nyankoface-pages-diff-add text-emerald-400">+</span>
                <span className="break-all">{path}</span>
              </p>
            ))}
          </div>
          <label className="mt-3 flex cursor-pointer items-start gap-3 rounded-xl border border-zinc-200 p-3 dark:border-zinc-700">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              className="mt-0.5 h-4 w-4 accent-indigo-700"
            />
            <span className="text-sm leading-5 text-zinc-700 dark:text-zinc-200">
              {ui(
                locale,
                '上記ファイルを作成または更新することを確認しました。既存ファイルは新しいPagesスターターで置き換わります。',
                'I reviewed these writes. Existing files at these paths will be replaced by the Pages starter.',
              )}
            </span>
          </label>
        </section>

        <button
          type="submit"
          disabled={!validTarget || !confirmed || deploying || inspection?.status === 'private'}
          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-indigo-700 px-5 text-sm font-bold text-white shadow-sm transition hover:bg-indigo-800 disabled:cursor-not-allowed disabled:bg-zinc-300 dark:disabled:bg-zinc-700"
        >
          <HfIcon name={deploying ? 'spinner' : 'pages'} className={`h-4 w-4 ${deploying ? 'animate-spin' : ''}`} />
          {deploying ? ui(locale, 'デプロイ中…', 'Deploying…') : ui(locale, 'Pagesをデプロイ', 'Deploy Pages')}
        </button>
      </form>

      <aside className="space-y-4">
        <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-bold text-zinc-950 dark:text-white">{ui(locale, '公開状態', 'Publishing status')}</h2>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${
              result?.status === 'published' || inspection?.status === 'published'
                ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                : result?.status === 'queued'
                  ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                  : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
            }`}>
              {result?.status === 'published' || inspection?.status === 'published'
                ? ui(locale, '公開中', 'Published')
                : result?.status === 'queued'
                  ? ui(locale, 'Actions実行待ち', 'Actions queued')
                  : ui(locale, '未公開', 'Not published')}
            </span>
          </div>
          {inspection ? (
            <div className="mt-4 space-y-2 text-sm text-zinc-600 dark:text-zinc-300">
              <p>
                {ui(locale, 'リポジトリ: ', 'Repository: ')}
                <strong className="text-zinc-900 dark:text-white">{inspection.owner}/{inspection.repo}</strong>
              </p>
              <p>{inspection.public ? ui(locale, '公開設定: public', 'Visibility: public') : ui(locale, '公開設定: private（公開不可）', 'Visibility: private (blocked)')}</p>
              {inspection.source ? <p>{ui(locale, '配信元: ', 'Source: ')}<code>{inspection.index_path}</code></p> : null}
              {inspection.reasons.map((reason) => <p key={reason} className="nyankoface-pages-reason text-amber-700 dark:text-amber-300">{reason}</p>)}
            </div>
          ) : (
            <p className="mt-3 text-sm leading-6 text-zinc-500 dark:text-zinc-400">
              {ui(locale, '対象を入力して公開条件を確認してください。Pagesにtopicは不要です。private repositoryは公開されません。', 'Enter a target and check it. Pages requires no topic, and private repositories are never published.')}
            </p>
          )}
        </section>

        {error ? (
          <section role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
            <p className="font-bold">{ui(locale, 'デプロイできませんでした', 'Deployment could not continue')}</p>
            <p className="mt-2 leading-6">{error}</p>
            {/sign-in|sign in/i.test(error) ? (
              <a href="/git/user/login" className="mt-3 inline-flex h-9 items-center rounded-lg bg-zinc-950 px-3 font-bold text-white dark:bg-white dark:text-zinc-950">
                {ui(locale, 'Forgejoへログイン', 'Sign in to Forgejo')}
              </a>
            ) : null}
          </section>
        ) : null}

        {result ? (
          <section className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900" data-pages-deploy-result={result.status}>
            <h2 className="text-base font-bold text-zinc-950 dark:text-white">{ui(locale, 'デプロイログ', 'Deployment log')}</h2>
            <ol className="mt-3 space-y-2 text-xs leading-5 text-zinc-600 dark:text-zinc-300">
              {result.logs.map((line, index) => (
                <li key={`${index}-${line}`} className="flex gap-2">
                  <span className="font-mono text-indigo-500">{String(index + 1).padStart(2, '0')}</span>
                  <span>{line}</span>
                </li>
              ))}
            </ol>
            {result.commits.length ? (
              <div className="mt-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">Commit SHA</p>
                <div className="mt-2 space-y-2">
                  {result.commits.map((commit) => (
                    <a
                      key={`${commit.sha}-${commit.path}`}
                      href={`/git/${result.owner}/${result.repo}/commit/${commit.sha}`}
                      className="flex items-center justify-between gap-3 rounded-lg bg-zinc-50 px-3 py-2 text-xs hover:bg-zinc-100 dark:bg-zinc-950 dark:hover:bg-zinc-800"
                    >
                      <span className="truncate">{commit.path}</span>
                      <code className="shrink-0 text-indigo-700 dark:text-indigo-300">{commit.sha.slice(0, 8)}</code>
                    </a>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              {result.status === 'published' ? (
                <a href={result.public_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-indigo-700 px-3 text-sm font-bold text-white hover:bg-indigo-800">
                  <HfIcon name="external" className="h-3.5 w-3.5" />
                  {ui(locale, 'サイトを見る', 'Visit site')}
                </a>
              ) : (
                <a href={result.actions_url} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-amber-500 px-3 text-sm font-bold text-zinc-950 hover:bg-amber-400">
                  <HfIcon name="play" className="h-3.5 w-3.5" />
                  {ui(locale, 'Actionsログを見る', 'Open Actions log')}
                </a>
              )}
              <button
                type="button"
                onClick={() => {
                  const shareable = shareablePublicUrl(result.public_url, publicOrigin);
                  if (shareable) void navigator.clipboard.writeText(shareable);
                }}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                <HfIcon name="link" className="h-3.5 w-3.5" />
                {ui(locale, 'URLをコピー', 'Copy URL')}
              </button>
            </div>
          </section>
        ) : null}

        <a
          href={locale === 'ja' ? 'https://sunwood-ai-labs.github.io/NyankoFace/ja/guide/pages' : 'https://sunwood-ai-labs.github.io/NyankoFace/guide/pages'}
          target="_blank"
          rel="noreferrer"
          className="nyankoface-pages-guide-card flex items-center justify-between gap-3 rounded-2xl border border-zinc-200 bg-white p-5 text-sm font-semibold text-indigo-700 hover:border-indigo-300 dark:border-zinc-800 dark:bg-zinc-900 dark:text-indigo-300"
        >
          {ui(locale, '正式なPages公開手順とトラブルシューティング', 'Canonical Pages workflow and troubleshooting')}
          <HfIcon name="external" className="h-3.5 w-3.5" />
        </a>
      </aside>
    </div>
  );
}
