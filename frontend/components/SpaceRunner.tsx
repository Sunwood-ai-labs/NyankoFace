'use client';

import { useEffect, useRef, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { useAuthSession } from './AuthSessionProvider';
import { useSpaceRuntime } from './SpaceRuntimeProvider';
import { ui } from '@/lib/i18n';
import {
  formatElapsedDuration,
  isSpaceGatewayErrorDocument,
  isSpaceGatewayPending,
  isSpaceRuntimePending,
  SPACE_IFRAME_RETRY_DELAY_MS,
  SPACE_IFRAME_TIMEOUT_MS,
  type SpaceIframePhase,
  type SpaceRuntimePhase,
} from '@/lib/space-runtime';

type SpaceOperation = 'start' | 'stop';
type OperationFeedback = {
  kind: 'success' | 'error';
  message: string;
  durationMs: number;
};

export default function SpaceRunner({
  owner,
  repo,
  description,
}: {
  owner: string;
  repo: string;
  description?: string | null;
}) {
  const { locale } = useLocale();
  const { auth } = useAuthSession();
  const runtime = useSpaceRuntime();
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState<SpaceOperation | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<OperationFeedback | null>(null);
  const [iframePhase, setIframePhase] = useState<SpaceIframePhase>('idle');
  const [iframeDurationMs, setIframeDurationMs] = useState<number | null>(null);
  const [iframeAttempt, setIframeAttempt] = useState(0);
  const [iframeSession, setIframeSession] = useState(0);
  const [iframeSourceReady, setIframeSourceReady] = useState(false);
  const iframeStartedAtRef = useRef(0);
  const iframeTimeoutRef = useRef<number | null>(null);
  const iframeRetryRef = useRef<number | null>(null);
  const iframeProbeRef = useRef<AbortController | null>(null);
  const iframeExpiredRef = useRef(false);
  const iframeRetryActionRef = useRef<(() => void) | null>(null);

  const controlBase = `/api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  const runUrl = `/run/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/`;
  const displayName = repo
    .replace(/-space$/i, '')
    .split(/[-_]+/)
    .map((part) => part.toLowerCase() === 'ocr' ? 'OCR' : part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

  useEffect(() => {
    if (iframeTimeoutRef.current !== null) {
      window.clearTimeout(iframeTimeoutRef.current);
      iframeTimeoutRef.current = null;
    }
    if (iframeRetryRef.current !== null) {
      window.clearTimeout(iframeRetryRef.current);
      iframeRetryRef.current = null;
    }
    iframeProbeRef.current?.abort();
    iframeProbeRef.current = null;
    iframeRetryActionRef.current = null;
    if (runtime?.phase !== 'running') {
      setIframeAttempt(0);
      setIframePhase('idle');
      setIframeDurationMs(null);
      setIframeSourceReady(false);
      return;
    }
    const startedAt = performance.now();
    iframeStartedAtRef.current = startedAt;
    iframeExpiredRef.current = false;
    setIframePhase('loading');
    setIframeDurationMs(null);
    setIframeSourceReady(false);
    let active = true;
    iframeTimeoutRef.current = window.setTimeout(() => {
      active = false;
      iframeExpiredRef.current = true;
      if (iframeRetryRef.current !== null) {
        window.clearTimeout(iframeRetryRef.current);
        iframeRetryRef.current = null;
      }
      iframeProbeRef.current?.abort();
      iframeProbeRef.current = null;
      setIframeSourceReady(false);
      setIframeDurationMs(Math.round(performance.now() - startedAt));
      setIframePhase('timeout');
      iframeTimeoutRef.current = null;
    }, SPACE_IFRAME_TIMEOUT_MS);

    const scheduleProbe = () => {
      if (!active || iframeRetryRef.current !== null) return;
      iframeRetryRef.current = window.setTimeout(() => {
        iframeRetryRef.current = null;
        if (!active) return;
        setIframeAttempt((value) => value + 1);
        void probe();
      }, SPACE_IFRAME_RETRY_DELAY_MS);
    };
    iframeRetryActionRef.current = scheduleProbe;

    const probe = async () => {
      const controller = new AbortController();
      iframeProbeRef.current = controller;
      try {
        const response = await fetch(
          runUrl,
          { cache: 'no-store', signal: controller.signal },
        );
        const contentType = response.headers.get('content-type') || '';
        const pendingBody = contentType.includes('application/json')
          ? await response.text()
          : '';
        if (response.ok && !isSpaceGatewayPending(pendingBody)) {
          if (active) setIframeSourceReady(true);
          return;
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        void reason;
      } finally {
        if (iframeProbeRef.current === controller) iframeProbeRef.current = null;
      }
      scheduleProbe();
    };
    void probe();

    return () => {
      active = false;
      iframeExpiredRef.current = true;
      if (iframeTimeoutRef.current !== null) {
        window.clearTimeout(iframeTimeoutRef.current);
        iframeTimeoutRef.current = null;
      }
      if (iframeRetryRef.current !== null) {
        window.clearTimeout(iframeRetryRef.current);
        iframeRetryRef.current = null;
      }
      iframeProbeRef.current?.abort();
      iframeProbeRef.current = null;
      iframeRetryActionRef.current = null;
    };
  }, [iframeSession, runUrl, runtime?.phase]);

  function responseDuration(response: Response, startedAt: number): number {
    const totalMetric = response.headers
      .get('server-timing')
      ?.split(',')
      .map((value) => value.trim())
      .find((value) => value.startsWith('total;'));
    const serverDuration = totalMetric?.match(/dur=([\d.]+)/)?.[1];
    return Math.round(serverDuration ? Number(serverDuration) : performance.now() - startedAt);
  }

  function actionError(action: SpaceOperation, statusCode: number): string {
    if (statusCode === 401) {
      return ui(locale, 'Forgejoにログインして再度お試しください。', 'Sign in to Forgejo, then try again.');
    }
    if (statusCode === 403) {
      return ui(locale, 'このSpaceへの書き込み権限が必要です。', 'Write permission on this Space is required.');
    }
    return action === 'start'
      ? ui(locale, `Spaceの起動に失敗しました (HTTP ${statusCode})`, `Failed to start this Space (HTTP ${statusCode})`)
      : ui(locale, `Spaceの一時停止に失敗しました (HTTP ${statusCode})`, `Failed to pause this Space (HTTP ${statusCode})`);
  }

  async function runAction(action: SpaceOperation) {
    if (busy) return;
    setBusy(true);
    setOperation(action);
    setErrorMsg(null);
    setFeedback(null);
    const startedAt = performance.now();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    try {
      const res = await fetch(`${controlBase}/${action}`, {
        method: 'POST',
        signal: controller.signal,
      });
      const durationMs = responseDuration(res, startedAt);
      if (!res.ok) {
        const message = actionError(action, res.status);
        setErrorMsg(message);
        setFeedback({ kind: 'error', message, durationMs });
        return;
      }
      const json = (await res.json().catch(() => null)) as Record<string, unknown> | null;
      if (json) runtime?.applyPayload(json);
      else await runtime?.refresh();
      const message = action === 'start'
        ? ui(locale, '起動要求を受け付けました。', 'Start request accepted.')
        : ui(locale, 'Spaceを一時停止しました。', 'Space paused.');
      setFeedback({ kind: 'success', message, durationMs });
    } catch (error) {
      const message = error instanceof DOMException && error.name === 'AbortError'
        ? ui(locale, '操作が30秒でタイムアウトしました。状態を確認してから再度お試しください。', 'The operation timed out after 30 seconds. Check the status before retrying.')
        : ui(locale, 'Space Runnerに接続できませんでした。', 'Could not connect to spaces-runner.');
      setErrorMsg(message);
      setFeedback({
        kind: 'error',
        message,
        durationMs: Math.round(performance.now() - startedAt),
      });
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
      setOperation(null);
    }
  }

  async function start() {
    await runAction('start');
  }

  async function stop() {
    await runAction('stop');
  }

  const phase = runtime?.phase || 'checking';
  const execution = runtime?.execution || 'local-cpu';
  const statusLabel: Record<SpaceRuntimePhase, string> = {
    checking: ui(locale, '状態を確認中', 'Checking runtime'),
    queued: ui(locale, '待機中', 'Queued'),
    leased: ui(locale, '割当済み', 'Leased'),
    building: ui(locale, 'ビルド中', 'Building'),
    starting: ui(locale, '起動中', 'Starting'),
    warming: ui(locale, '準備中', 'Warming up'),
    stopping: ui(locale, '停止中', 'Stopping'),
    stopped: ui(locale, 'オンデマンド', 'On demand'),
    running: ui(locale, '実行中', 'Running'),
    offline: ui(locale, 'オフライン', 'Offline'),
    unavailable: ui(locale, '利用不可', 'Unavailable'),
    failed: ui(locale, '失敗', 'Failed'),
    error: ui(locale, 'エラー', 'Error'),
  };

  const statusColor: Record<SpaceRuntimePhase, string> = {
    checking: 'bg-sky-100 text-sky-800',
    queued: 'bg-amber-200 text-amber-800',
    leased: 'bg-amber-200 text-amber-800',
    building: 'bg-amber-200 text-amber-800',
    starting: 'bg-amber-200 text-amber-800',
    warming: 'bg-amber-200 text-amber-800',
    stopping: 'bg-amber-200 text-amber-800',
    stopped: 'bg-zinc-200 text-zinc-600',
    running: 'bg-green-200 text-green-800',
    offline: 'bg-red-200 text-red-800',
    unavailable: 'bg-red-200 text-red-800',
    failed: 'bg-red-200 text-red-800',
    error: 'bg-red-200 text-red-800',
  };

  return (
    <div
      className="nyankoface-space-runner overflow-hidden bg-white dark:bg-zinc-950"
      aria-busy={busy}
      data-operation-state={operation || 'idle'}
      data-runtime-phase={phase}
      data-runtime-request-ms={runtime?.requestDurationMs ?? undefined}
      data-iframe-phase={iframePhase}
      data-iframe-duration-ms={iframeDurationMs ?? undefined}
    >
      <div className="nyankoface-space-runner-toolbar flex flex-wrap items-center gap-2 border-b border-zinc-100 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950">
        <div className="flex min-w-0 items-center gap-2">
          <HfIcon name="space" className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">App</span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${statusColor[phase]}`}>
            {execution === 'remote-gpu' ? 'GPU' : 'CPU'} · {statusLabel[phase]}
          </span>
        </div>

        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={start}
            disabled={busy || phase === 'running' || isSpaceRuntimePending(phase)}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-950 px-3 text-sm font-semibold text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-100 dark:text-zinc-950"
          >
            <HfIcon
              name={operation === 'start' ? 'spinner' : 'play'}
              className={`h-3.5 w-3.5 ${operation === 'start' ? 'animate-spin' : ''}`}
            />
            {operation === 'start'
              ? ui(locale, '起動を受付中…', 'Starting…')
              : phase === 'running'
                ? ui(locale, '実行中', 'Running')
                : ui(locale, 'Spaceを起動', 'Start this Space')}
          </button>
          {auth.status === 'authenticated' ? (
            <button
              type="button"
              onClick={stop}
              disabled={busy || phase === 'stopped'}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 px-3 text-sm font-medium hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              <HfIcon
                name={operation === 'stop' ? 'spinner' : 'pause'}
                className={`h-3.5 w-3.5 ${operation === 'stop' ? 'animate-spin' : ''}`}
              />
              {operation === 'stop' ? ui(locale, '一時停止中…', 'Pausing…') : ui(locale, '一時停止', 'Pause')}
            </button>
          ) : null}
        </div>
      </div>

      {feedback && (
        <div
          role={feedback.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          data-feedback-kind={feedback.kind}
          className={`mx-4 mt-3 flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${
            feedback.kind === 'error'
              ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
              : 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
          }`}
        >
          <span>{feedback.message}</span>
          <span className="shrink-0 font-mono text-xs opacity-75">{feedback.durationMs} ms</span>
        </div>
      )}

      {errorMsg && <span className="sr-only">{errorMsg}</span>}

      {phase === 'running' ? (
        <div className="nyankoface-space-frame-stage relative">
          {iframeSourceReady ? <iframe
            key={iframeAttempt}
            src={runUrl}
            className={`nyankoface-space-frame w-full border-0 transition-opacity duration-300 ${iframePhase === 'ready' ? 'opacity-100' : 'opacity-0'}`}
            title={`${owner}/${repo} Space`}
            onLoad={(event) => {
              if (iframeExpiredRef.current) return;
              const documentText = event.currentTarget.contentDocument?.body?.textContent;
              const contentType = event.currentTarget.contentDocument?.contentType;
              if (isSpaceGatewayErrorDocument(documentText, contentType)) {
                setIframeSourceReady(false);
                iframeRetryActionRef.current?.();
                return;
              }
              if (iframeTimeoutRef.current !== null) {
                window.clearTimeout(iframeTimeoutRef.current);
                iframeTimeoutRef.current = null;
              }
              const startedAt = iframeStartedAtRef.current || performance.now();
              setIframeDurationMs(Math.round(performance.now() - startedAt));
              setIframePhase('ready');
            }}
            onError={() => {
              if (iframeExpiredRef.current) return;
              if (iframeTimeoutRef.current !== null) {
                window.clearTimeout(iframeTimeoutRef.current);
                iframeTimeoutRef.current = null;
              }
              const startedAt = iframeStartedAtRef.current || performance.now();
              setIframeDurationMs(Math.round(performance.now() - startedAt));
              setIframePhase('error');
            }}
          /> : null}
          {iframePhase !== 'ready' ? (
            <div className="nyankoface-space-stage absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#090b12] px-6 text-center text-zinc-300" role={iframePhase === 'error' || iframePhase === 'timeout' ? 'alert' : 'status'}>
              <HfIcon name={iframePhase === 'idle' || iframePhase === 'loading' ? 'spinner' : 'fire'} className={`h-8 w-8 text-violet-300 ${iframePhase === 'idle' || iframePhase === 'loading' ? 'animate-spin' : ''}`} />
              <div>
                <p className="font-semibold">
                  {iframePhase === 'idle' || iframePhase === 'loading'
                    ? ui(locale, 'アプリへ接続中', 'Connecting to the app')
                    : iframePhase === 'timeout'
                      ? ui(locale, 'アプリの応答がタイムアウトしました', 'The app response timed out')
                      : ui(locale, 'アプリへ接続できませんでした', 'Could not connect to the app')}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  {ui(locale, 'runtimeの状態とアプリ画面は別々に確認しています。', 'Runtime status and app readiness are checked separately.')}
                </p>
              </div>
              {iframePhase === 'timeout' || iframePhase === 'error' ? (
                <button type="button" onClick={() => {
                  setIframeAttempt((value) => value + 1);
                  setIframeSession((value) => value + 1);
                }} className="rounded-lg border border-violet-300/40 px-4 py-2 text-sm font-semibold text-violet-100 hover:bg-violet-400/10">
                  {ui(locale, '接続を再試行', 'Retry connection')}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="nyankoface-space-stage relative flex min-h-[calc(100vh-50px)] flex-col overflow-hidden bg-[#090b12] px-7 py-6 text-zinc-400">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_55%,rgba(103,90,190,0.58),rgba(45,42,78,0.44)_16%,rgba(9,11,18,0.98)_46%)]" />
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,rgba(255,255,255,0.025)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:18px_18px]" />
          <div className="relative z-10 flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="max-w-[360px] text-2xl font-bold leading-tight text-zinc-300">
                  {displayName}
                </h2>
                <span className="grid h-6 w-6 place-items-center rounded-full border border-white/20 text-xs text-zinc-400">i</span>
              </div>
              <p className="mt-3 max-w-[440px] text-lg leading-7 text-zinc-300">
                {description || ui(locale, `${owner}/${repo}として公開されたAIアプリです。`, `AI application published as ${owner}/${repo}.`)}
              </p>
              <p className="mt-4 text-[11px] font-semibold uppercase tracking-normal text-zinc-500">
                {ui(locale, '実行基盤', 'Powered by')} <span className="normal-case text-zinc-300">NyankoFace Runner</span>
              </p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={start}
                disabled={busy || isSpaceRuntimePending(phase)}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-4 text-sm font-semibold text-zinc-100 hover:bg-white/10 disabled:cursor-wait disabled:opacity-70"
              >
                <HfIcon name={operation === 'start' ? 'spinner' : 'play'} className={`h-3.5 w-3.5 ${operation === 'start' ? 'animate-spin' : ''}`} />
                {operation === 'start' ? ui(locale, '起動中…', 'Starting…') : ui(locale, '起動', 'Start')}
              </button>
              <a
                href={`/git/${owner}/${repo}/src/branch/main`}
                aria-label={ui(locale, 'Spaceのファイルを見る', 'View Space files')}
                title={ui(locale, 'Spaceのファイルを見る', 'View Space files')}
                className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10"
              >
                <HfIcon name="file" className="h-4 w-4" />
              </a>
              {auth.status === 'authenticated' ? (
                <a
                  href={`/git/${owner}/${repo}/settings`}
                  aria-label={ui(locale, 'ForgejoでSpaceの設定を開く', 'Open Space settings in Forgejo')}
                  title={ui(locale, 'ForgejoでSpaceの設定を開く', 'Open Space settings in Forgejo')}
                  className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10"
                >
                  <HfIcon name="gear" className="h-4 w-4" />
                </a>
              ) : null}
            </div>
          </div>

          <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-8 text-center">
            <button
              type="button"
              onClick={start}
              disabled={busy || isSpaceRuntimePending(phase)}
              aria-label={ui(locale, 'このSpaceを起動', 'Start this Space')}
              title={ui(locale, 'このSpaceを起動', 'Start this Space')}
              className="group relative grid h-56 w-56 place-items-center rounded-full border border-violet-300/45 bg-violet-500/20 shadow-[0_0_64px_rgba(111,91,255,0.45),inset_0_0_54px_rgba(168,145,255,0.24)] transition hover:scale-[1.02] disabled:cursor-wait disabled:opacity-70 max-sm:h-44 max-sm:w-44"
            >
              <span className="absolute inset-[-16px] rounded-full border border-violet-300/10" />
              <HfIcon
                name={operation === 'start' ? 'spinner' : 'play'}
                className={`h-10 w-10 text-violet-100 transition group-hover:scale-110 ${operation === 'start' ? 'animate-spin' : ''}`}
              />
            </button>
            <div className="space-y-2">
              <p className="text-[12px] font-semibold uppercase tracking-[0.28em] text-zinc-500">
                {operation === 'start'
                  ? ui(locale, '起動要求を送信中', 'Sending start request')
                  : isSpaceRuntimePending(phase)
                    ? `${statusLabel[phase]} · ${formatElapsedDuration(runtime?.elapsedMs || 0)}`
                    : ['offline', 'unavailable', 'failed', 'error'].includes(phase)
                      ? statusLabel[phase]
                      : ui(locale, 'タップして起動', 'Tap to start')}
              </p>
              {runtime?.error ? (
                <button type="button" onClick={() => void runtime.refresh()} disabled={runtime.checking} className="rounded-md border border-white/15 px-3 py-1.5 text-xs font-semibold text-zinc-300 hover:bg-white/5 disabled:opacity-60">
                  {runtime.checking ? ui(locale, '再確認中…', 'Checking…') : ui(locale, '状態を再確認', 'Check again')}
                </button>
              ) : null}
              <p className="mx-auto max-w-[300px] text-xs leading-5 text-zinc-500">
                {ui(locale, '公開Spaceはログインなしでオンデマンド起動できます。', 'Public Spaces can be started on demand without signing in.')}
              </p>
            </div>
          </div>

          <div className="relative z-10 pb-1 text-center text-xs text-zinc-600">
            {ui(locale, '提供', 'Powered by')} {owner}/{repo}
          </div>
        </div>
      )}
    </div>
  );
}
