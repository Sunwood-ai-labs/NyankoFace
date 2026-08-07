'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import HfIcon from './HfIcon';
import { Locale, ui } from '@/lib/i18n';
import {
  buildPipelineDispatchRequest,
  pipelineTargetRevision,
} from '@/lib/pipeline';

type PipelineWorkflow = {
  name: string;
  path: string;
  sha: string;
};

type PipelineRun = {
  id: number;
  run_number: number;
  name: string;
  display_title: string;
  status: string;
  event: string;
  environment: 'preview' | 'staging' | 'production';
  head_branch: string;
  head_sha: string;
  deployed_revision?: string;
  run_started_at?: string;
  updated_at?: string;
  actor?: string;
  forgejo_url: string;
  environment_url?: string;
  deployment?: {
    source_sha?: string;
    artifact_sha256?: string;
  };
};

type PipelineAudit = {
  id: number;
  action: string;
  actor: string;
  run_number?: number;
  environment?: string;
  revision?: string;
  created_at: string;
};

type PipelineSummary = {
  workflows: PipelineWorkflow[];
  runs: PipelineRun[];
  audit: PipelineAudit[];
  environments: string[];
  runner_targets: Array<{
    value: string;
    label: string;
    available?: boolean;
    status?: string;
  }>;
};

type RunDetail = {
  state?: {
    run?: {
      title?: string;
      status?: string;
      canCancel?: boolean;
      canApprove?: boolean;
      canRerun?: boolean;
      approvalUrl?: string;
      done?: boolean;
    };
  };
  jobs?: Array<{
    id: number;
    name: string;
    status: string;
    duration: string;
    runner?: string;
    steps: Array<{ summary: string; status: string; duration: string }>;
    logs: Array<{ step: number; index: number; message: string }>;
  }>;
};

const STATUS_STYLE: Record<string, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300',
  running: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300',
  waiting: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300',
  blocked: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300',
  failure: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300',
  cancelled: 'border-zinc-200 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300',
};

function messageFrom(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== 'object') return fallback;
  const value = payload as {
    error?: string;
    detail?: string | { message?: string };
  };
  if (typeof value.error === 'string') return value.error;
  if (typeof value.detail === 'string') return value.detail;
  if (typeof value.detail?.message === 'string') return value.detail.message;
  return fallback;
}

function statusLabel(status: string, locale: Locale): string {
  if (locale !== 'ja') return status;
  return ({
    success: '成功',
    running: '実行中',
    waiting: '待機中',
    blocked: '確認待ち',
    queued: '待機中',
    failure: '失敗',
    cancelled: 'キャンセル済み',
    timed_out: 'タイムアウト',
    skipped: 'スキップ',
  } as Record<string, string>)[status.toLowerCase()] || status;
}

function eventLabel(event: string, locale: Locale): string {
  if (locale !== 'ja') return event;
  return ({
    push: 'プッシュ',
    pull_request: 'プルリクエスト',
    workflow_dispatch: '手動 / API',
    schedule: 'スケジュール',
    release: 'リリース',
  } as Record<string, string>)[event.toLowerCase()] || event;
}

function StatusBadge({ status, locale }: { status: string; locale: Locale }) {
  const normalized = status.toLowerCase();
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-bold ${STATUS_STYLE[normalized] || STATUS_STYLE.cancelled}`}>
      {statusLabel(status, locale)}
    </span>
  );
}

export default function PipelinePanel({
  owner,
  repo,
  defaultBranch,
  locale,
}: {
  owner: string;
  repo: string;
  defaultBranch: string;
  locale: Locale;
}) {
  const base = `/api/pipelines/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  const [summary, setSummary] = useState<PipelineSummary | null>(null);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [environment, setEnvironment] = useState('staging');
  const [runner, setRunner] = useState('node20');
  const [workflow, setWorkflow] = useState('');
  const [targetRevision, setTargetRevision] = useState(defaultBranch);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [visibleRunCount, setVisibleRunCount] = useState(8);
  const [wrapLogs, setWrapLogs] = useState(true);
  const [openJobs, setOpenJobs] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const detailRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    const response = await fetch(base, { cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(messageFrom(payload, ui(locale, 'パイプラインを取得できません。', 'Could not load pipelines.')));
    }
    const next = payload as PipelineSummary;
    setSummary(next);
    setWorkflow((current) => current || next.workflows[0]?.name || '');
  }, [base, locale]);

  useEffect(() => {
    refresh()
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoading(false));
  }, [refresh]);

  const loadRun = useCallback(async (runNumber: number, showLoading = true) => {
    setSelectedRun(runNumber);
    if (showLoading) setDetail(null);
    setError(null);
    try {
      const response = await fetch(`${base}/runs/${runNumber}`, { cache: 'no-store' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(messageFrom(payload, ui(locale, '実行ログを取得できません。', 'Could not load run logs.')));
      }
      const nextDetail = payload as RunDetail;
      setDetail(nextDetail);
      if (showLoading) {
        setOpenJobs(Object.fromEntries(
          (nextDetail.jobs || []).map((job) => [
            job.id,
            ['failure', 'running', 'waiting', 'timed_out'].includes(
              job.status.toLowerCase(),
            ),
          ]),
        ));
      }
      if (showLoading && window.matchMedia('(max-width: 1279px)').matches) {
        window.requestAnimationFrame(() => {
          detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          detailRef.current?.focus({ preventScroll: true });
        });
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [base, locale]);

  useEffect(() => {
    const active = summary?.runs.some((run) =>
      ['waiting', 'running', 'blocked', 'queued'].includes(run.status.toLowerCase()));
    if (!active) return;
    const timer = window.setInterval(() => {
      refresh().catch((reason) =>
        setError(reason instanceof Error ? reason.message : String(reason)));
      if (selectedRun) void loadRun(selectedRun, false);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [loadRun, refresh, selectedRun, summary?.runs]);

  async function mutate(path: string, body?: object) {
    setBusy(path);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(`${base}/${path}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(messageFrom(payload, ui(locale, '操作に失敗しました。', 'The operation failed.')));
      }
      const approvalUrl = (
        payload
        && typeof payload === 'object'
        && 'approval_url' in payload
        && typeof payload.approval_url === 'string'
      ) ? payload.approval_url : null;
      if (approvalUrl) {
        window.location.assign(approvalUrl);
        return;
      }
      setNotice(ui(locale, '操作を受け付けました。', 'The operation was accepted.'));
      await refresh();
      if (selectedRun) await loadRun(selectedRun);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  function dispatchRun() {
    if (
      environment === 'production'
      && !window.confirm(ui(
        locale,
        '本番環境へ反映します。対象ブランチ／タグ／コミットを確認しましたか？',
        'Deploy to production. Have you verified the target branch, tag, or commit?',
      ))
    ) {
      return;
    }
    void mutate('dispatch', buildPipelineDispatchRequest({
      workflow,
      defaultBranch,
      targetRevision,
      environment,
      runner,
    }));
  }

  async function refreshNow() {
    setBusy('refresh');
    setNotice(null);
    try {
      await refresh();
      if (selectedRun) await loadRun(selectedRun, false);
      setNotice(ui(locale, '最新の状態へ更新しました。', 'Pipeline status refreshed.'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  const selected = useMemo(
    () => summary?.runs.find((run) => run.run_number === selectedRun) || null,
    [selectedRun, summary],
  );
  const selectedRunner = summary?.runner_targets?.find(
    (item) => item.value === runner,
  );

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="grid min-h-60 place-items-center text-sm text-zinc-500">
        <HfIcon name="spinner" className="h-5 w-5 animate-spin" />
        <span className="sr-only">
          {ui(locale, 'パイプラインを読み込んでいます。', 'Loading pipelines.')}
        </span>
      </div>
    );
  }

  return (
    <section
      className="mx-auto w-full max-w-6xl space-y-6 pb-12"
      data-pipeline-panel
      aria-busy={busy !== null}
    >
      <header className="flex flex-col gap-4 rounded-2xl border border-zinc-200 bg-zinc-50/80 p-5 dark:border-zinc-800 dark:bg-zinc-900/60 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="nyankoface-pipeline-kicker flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-cyan-700 dark:text-cyan-300">
            <HfIcon name="code" className="h-4 w-4" />
            NyankoFace Pipelines
          </div>
          <h2 className="mt-2 text-xl font-bold text-zinc-950 dark:text-zinc-100">
            {ui(locale, 'ビルド・テスト・デプロイ', 'Build, test, and deploy')}
          </h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-600 dark:text-zinc-400">
            {ui(
              locale,
              'Forgejo Actionsの実行状態、ジョブ、ログ、PRの信頼確認、再実行、rollbackを一画面で管理します。',
              'Manage Forgejo Actions runs, jobs, logs, PR trust review, retries, and rollbacks in one place.',
            )}
          </p>
        </div>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => void refreshNow()}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-xl border border-zinc-200 bg-white px-4 text-sm font-bold text-zinc-700 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200"
        >
          <HfIcon name={busy === 'refresh' ? 'spinner' : 'automation'} className={`h-3.5 w-3.5 ${busy === 'refresh' ? 'animate-spin' : ''}`} />
          {ui(locale, '更新', 'Refresh')}
        </button>
      </header>

      {error ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
          {error.toLowerCase().includes('sign-in') ? (
            <a href="/git/user/login" className="ml-2 font-bold underline">
              {ui(locale, 'ログイン', 'Sign in')}
            </a>
          ) : null}
        </div>
      ) : null}
      {notice ? (
        <div role="status" aria-live="polite" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300">
          {notice}
        </div>
      ) : null}

      {!summary?.workflows.length ? (
        <div className="rounded-2xl border border-dashed border-zinc-300 p-8 text-center dark:border-zinc-700">
          <HfIcon name="space" className="mx-auto h-8 w-8 text-cyan-500" />
          <h3 className="mt-3 font-bold">{ui(locale, 'パイプラインは未設定です', 'No pipeline configured')}</h3>
          <p className="mx-auto mt-2 max-w-xl text-sm text-zinc-500">
            {ui(
              locale,
              'push・Pull Request・手動実行に対応する最小構成をリポジトリへ追加できます。',
              'Install a minimal workflow for push, pull request, and manual triggers.',
            )}
          </p>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => mutate('install')}
            className="nyankoface-pipeline-primary mt-5 inline-flex h-11 items-center gap-2 rounded-xl bg-zinc-950 px-5 text-sm font-bold text-white hover:bg-zinc-800 disabled:opacity-50 dark:bg-cyan-300 dark:text-zinc-950"
          >
            <HfIcon name="plus" className="h-4 w-4" />
            {ui(locale, 'スターターパイプラインを追加', 'Install starter pipeline')}
          </button>
        </div>
      ) : (
        <div
          className="grid gap-4 rounded-2xl border border-zinc-200 p-5 dark:border-zinc-800 lg:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_minmax(210px,230px)_160px_minmax(170px,1fr)_130px]"
          data-pipeline-dispatch
        >
          <label className="grid gap-1.5 text-xs font-bold text-zinc-500">
            {ui(locale, 'ワークフロー', 'Workflow')}
            <select
              value={workflow}
              onChange={(event) => setWorkflow(event.target.value)}
              className="h-11 min-w-0 rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            >
              {summary.workflows.map((item) => (
                <option key={item.path} value={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-xs font-bold text-zinc-500">
            {ui(locale, '実行基盤', 'Runner')}
            <select
              data-pipeline-runner
              value={runner}
              onChange={(event) => setRunner(event.target.value)}
              className="h-11 rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            >
              {(summary.runner_targets || [
                { value: 'node20', label: 'CPU · Node.js 20' },
                { value: 'gpu', label: 'GPU · CUDA' },
              ]).map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                  disabled={item.available === false}
                >
                  {item.label}
                  {item.status === 'online'
                    ? ui(locale, ' · オンライン', ' · Online')
                    : item.available === false
                      ? ui(locale, ' · 利用不可', ' · Unavailable')
                      : ''}
                </option>
              ))}
            </select>
            {selectedRunner?.available === false ? (
              <span className="font-normal text-amber-700 dark:text-amber-300">
                {ui(locale, '現在利用できるrunnerがありません。', 'No matching runner is currently online.')}
              </span>
            ) : null}
          </label>
          <label className="grid gap-1.5 text-xs font-bold text-zinc-500">
            {ui(locale, '環境', 'Environment')}
            <select
              value={environment}
              onChange={(event) => setEnvironment(event.target.value)}
              className="h-11 rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            >
              {(summary.environments || ['preview', 'staging', 'production']).map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-xs font-bold text-zinc-500">
            {ui(
              locale,
              '対象ブランチ / タグ / コミット',
              'Target branch / tag / commit',
            )}
            <input
              value={targetRevision}
              onChange={(event) => setTargetRevision(event.target.value)}
              className="h-11 rounded-xl border border-zinc-200 bg-white px-3 font-mono text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            />
            <span className="font-normal text-zinc-400">
              {ui(
                locale,
                `ワークフローは ${defaultBranch} から実行します。`,
                `The workflow runs from ${defaultBranch}.`,
              )}
            </span>
          </label>
          <button
            type="button"
            disabled={!workflow || busy !== null || selectedRunner?.available === false}
            onClick={dispatchRun}
            className="mt-auto inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-cyan-600 px-4 text-sm font-bold text-white hover:bg-cyan-500 disabled:opacity-50"
          >
            <HfIcon name="play" className="h-4 w-4" />
            {ui(locale, '実行', 'Run')}
          </button>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-bold">{ui(locale, '実行履歴', 'Run history')}</h3>
            <span className="text-xs text-zinc-500">
              {ui(locale, `${summary?.runs.length || 0}件`, `${summary?.runs.length || 0} runs`)}
            </span>
          </div>
          <div className="space-y-2">
            {!summary?.runs.length ? (
              <p className="rounded-xl border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
                {ui(locale, 'まだ実行履歴がありません。', 'No pipeline runs yet.')}
              </p>
            ) : summary.runs.slice(0, visibleRunCount).map((run) => {
              const target = pipelineTargetRevision({
                deploymentSourceSha: run.deployment?.source_sha,
                deployedRevision: run.deployed_revision,
                headSha: run.head_sha,
              });
              return (
              <button
                key={run.id}
                type="button"
                data-pipeline-run={run.run_number}
                aria-pressed={selectedRun === run.run_number}
                onClick={() => void loadRun(run.run_number)}
                className={`w-full rounded-xl border p-4 text-left transition ${
                  selectedRun === run.run_number
                    ? 'border-cyan-400 bg-cyan-50/60 ring-2 ring-cyan-100 dark:bg-cyan-950/20 dark:ring-cyan-950'
                    : 'border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900'
                }`}
              >
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-bold">{run.display_title || run.name}</p>
                    <p className="mt-1 truncate font-mono text-xs text-zinc-500">
                      #{run.run_number} · {target.slice(0, 12)}
                    </p>
                  </div>
                  <StatusBadge status={run.status} locale={locale} />
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-zinc-500">
                  <span className="rounded-md bg-zinc-100 px-2 py-1 dark:bg-zinc-800">{run.environment}</span>
                  <span className="rounded-md bg-zinc-100 px-2 py-1 dark:bg-zinc-800">{eventLabel(run.event, locale)}</span>
                  {run.actor ? (
                    <span className="rounded-md bg-zinc-100 px-2 py-1 dark:bg-zinc-800">
                      @{run.actor}
                    </span>
                  ) : null}
                  {run.environment_url ? (
                    <span className="inline-flex items-center gap-1 rounded-md bg-cyan-50 px-2 py-1 font-bold text-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-300">
                      <HfIcon name="external" className="h-3 w-3" />
                      {ui(locale, '環境URL準備済み', 'Environment ready')}
                    </span>
                  ) : null}
                </div>
              </button>
              );
            })}
          </div>
          {(summary?.runs.length || 0) > visibleRunCount ? (
            <button
              type="button"
              onClick={() => setVisibleRunCount((count) => count + 8)}
              className="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-xl border border-zinc-200 px-4 text-sm font-bold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              {ui(locale, 'さらに8件を表示', 'Show 8 more runs')}
            </button>
          ) : null}
        </div>

        <div ref={detailRef} tabIndex={-1} className="min-w-0 scroll-mt-24 focus:outline-none">
          <h3 className="mb-3 font-bold">{ui(locale, 'ジョブとログ', 'Jobs and logs')}</h3>
          {!selected ? (
            <div className="grid min-h-64 place-items-center rounded-2xl border border-dashed border-zinc-300 text-sm text-zinc-500 dark:border-zinc-700">
              {ui(locale, '実行を選択すると詳細を表示します。', 'Select a run to inspect details.')}
            </div>
          ) : (
            <div
              className="overflow-hidden rounded-2xl border border-zinc-200 dark:border-zinc-800"
              data-pipeline-detail={selected.run_number}
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 p-4 dark:border-zinc-800">
                <div>
                  <p className="font-bold">#{selected.run_number} {selected.display_title}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {selected.environment} · {eventLabel(selected.event, locale)}
                  </p>
                  <p className="mt-1 break-all font-mono text-[11px] text-zinc-400">
                    {ui(locale, '対象', 'Target')}: {pipelineTargetRevision({
                      deploymentSourceSha: selected.deployment?.source_sha,
                      deployedRevision: selected.deployed_revision,
                      headSha: selected.head_sha,
                    }).slice(0, 16)}
                    {' · '}
                    {ui(locale, 'ワークフロー', 'Workflow')}: {selected.head_branch}
                    {selected.actor ? ` · @${selected.actor}` : ''}
                    {selected.run_started_at
                      ? ` · ${new Date(selected.run_started_at).toLocaleString(
                        locale === 'ja' ? 'ja-JP' : 'en-US',
                      )}`
                      : ''}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    aria-pressed={wrapLogs}
                    onClick={() => setWrapLogs((current) => !current)}
                    className="min-h-11 rounded-lg border border-zinc-200 px-3 py-2 text-xs font-bold dark:border-zinc-700"
                  >
                    {wrapLogs
                      ? ui(locale, 'ログ折返し: ON', 'Log wrap: on')
                      : ui(locale, 'ログ折返し: OFF', 'Log wrap: off')}
                  </button>
                  <a
                    href={selected.forgejo_url}
                    className="inline-flex min-h-11 items-center rounded-lg border border-zinc-200 px-3 py-2 text-xs font-bold hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
                  >
                    {ui(locale, 'Forgejoで開く', 'Open in Forgejo')}
                  </a>
                  {selected.environment_url ? (
                    <a
                      href={selected.environment_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      data-pipeline-environment-link={selected.environment}
                      className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-xs font-bold text-white shadow-sm shadow-cyan-900/10 transition hover:bg-cyan-500"
                    >
                      <HfIcon name="external" className="h-3.5 w-3.5" />
                      {ui(locale, '環境を開く', 'Open environment')}
                    </a>
                  ) : null}
                  {detail?.state?.run?.canApprove && detail.state.run.approvalUrl ? (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => mutate(`runs/${selected.run_number}/approve`)}
                      className="min-h-11 rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50"
                    >
                      {ui(locale, 'PRの信頼を確認', 'Review PR trust')}
                    </button>
                  ) : null}
                  {detail?.state?.run?.canCancel ? (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => {
                        if (window.confirm(ui(locale, 'この実行をキャンセルしますか？', 'Cancel this run?'))) {
                          void mutate(`runs/${selected.run_number}/cancel`);
                        }
                      }}
                      className="min-h-11 rounded-lg border border-red-200 px-3 py-2 text-xs font-bold text-red-600 disabled:opacity-50"
                    >
                      {ui(locale, 'キャンセル', 'Cancel')}
                    </button>
                  ) : null}
                  {detail?.state?.run?.canRerun ? (
                    <button type="button" disabled={busy !== null} onClick={() => mutate(`runs/${selected.run_number}/rerun`)} className="min-h-11 rounded-lg border border-zinc-200 px-3 py-2 text-xs font-bold disabled:opacity-50 dark:border-zinc-700">
                      {ui(locale, '同じ実行を再試行', 'Retry this run')}
                    </button>
                  ) : null}
                  {selected.status === 'success' && selected.environment === 'production' ? (
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => {
                        if (window.confirm(ui(locale, 'この成功versionへ戻しますか？', 'Roll back to this successful version?'))) {
                          void mutate(`runs/${selected.run_number}/rollback`);
                        }
                      }}
                      className="min-h-11 rounded-lg border border-amber-300 px-3 py-2 text-xs font-bold text-amber-700 disabled:opacity-50"
                    >
                      {ui(locale, 'この版へ戻す', 'Roll back')}
                    </button>
                  ) : null}
                </div>
              </div>
              {!detail ? (
                <div className="grid min-h-52 place-items-center">
                  <HfIcon name="spinner" className="h-5 w-5 animate-spin text-zinc-400" />
                </div>
              ) : (
                <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {(detail.jobs || []).map((job) => (
                    <details
                      key={job.id}
                      open={openJobs[job.id] ?? false}
                      onToggle={(event) => {
                        const isOpen = event.currentTarget.open;
                        setOpenJobs((current) => (
                          current[job.id] === isOpen
                            ? current
                            : { ...current, [job.id]: isOpen }
                        ));
                      }}
                      className="group"
                    >
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-4">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-bold">{job.name}</p>
                          <p className="mt-1 flex flex-wrap gap-x-2 text-xs text-zinc-500">
                            {job.duration ? <span>{job.duration}</span> : null}
                            {job.runner ? <span>{job.runner}</span> : null}
                          </p>
                        </div>
                        <StatusBadge status={job.status} locale={locale} />
                      </summary>
                      <div className="border-t border-zinc-100 bg-zinc-950 p-4 dark:border-zinc-800">
                        {['failure', 'cancelled', 'timed_out'].includes(job.status.toLowerCase()) ? (
                          <button
                            type="button"
                            disabled={busy !== null}
                            onClick={() => mutate(
                              `runs/${selected.run_number}/jobs/${job.id}/rerun`,
                            )}
                            className="mb-3 inline-flex h-11 items-center gap-2 rounded-lg border border-amber-400/50 px-3 text-xs font-bold text-amber-200 hover:bg-amber-400/10 disabled:opacity-50"
                          >
                            <HfIcon name="automation" className="h-3.5 w-3.5" />
                            {ui(locale, '失敗したジョブを再実行', 'Rerun failed job')}
                          </button>
                        ) : null}
                        <div className="mb-3 flex flex-wrap gap-2">
                          {job.steps.map((step, index) => (
                            <span key={`${step.summary}-${index}`} className="nyankoface-pipeline-step-chip rounded-md bg-zinc-800 px-2 py-1 text-xs text-white">
                              {step.summary} · {statusLabel(step.status, locale)}
                              {step.duration ? ` · ${step.duration}` : ''}
                            </span>
                          ))}
                        </div>
                        {!wrapLogs ? (
                          <p className="mb-2 text-xs text-zinc-300">
                            {ui(locale, '横にスクロールして長い行を確認できます。', 'Scroll horizontally to inspect long lines.')}
                          </p>
                        ) : null}
                        <pre className={`max-h-96 overflow-auto font-mono text-xs leading-5 text-zinc-200 ${
                          wrapLogs ? 'whitespace-pre-wrap break-words' : 'whitespace-pre'
                        }`}>
                          {job.logs.length
                            ? job.logs.map((line) => line.message).join('\n')
                            : ui(locale, 'ログはまだありません。', 'No logs available yet.')}
                        </pre>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <details className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
        <summary className="cursor-pointer text-sm font-bold">
          {ui(locale, '監査履歴', 'Audit history')} ({summary?.audit.length || 0})
        </summary>
        <div className="mt-4 divide-y divide-zinc-100 text-xs dark:divide-zinc-800">
          {(summary?.audit || []).map((entry) => (
            <div key={entry.id} className="grid gap-1 py-3 sm:grid-cols-[130px_1fr_auto]">
              <strong>{entry.action}</strong>
              <span className="text-zinc-500">
                {entry.actor} · {entry.environment || '—'} · {entry.revision?.slice(0, 12) || '—'}
              </span>
              <time className="text-zinc-400">{new Date(entry.created_at).toLocaleString()}</time>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
