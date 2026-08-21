'use client';

import { useEffect, useRef, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { useAuthSession } from './AuthSessionProvider';
import { useSpaceRuntime } from './SpaceRuntimeProvider';
import { ui } from '@/lib/i18n';
import {
  formatElapsedDuration,
  getSpaceRuntimeState,
  isSpaceGatewayErrorDocument,
  isSpaceGatewayPending,
  isSpaceRuntimePending,
  SPACE_IFRAME_RETRY_DELAY_MS,
  SPACE_IFRAME_TIMEOUT_MS,
  type SpaceIframePhase,
  type SpaceRuntimePhase,
  type SpaceRuntimeStateKind,
  type SpaceRuntimeStep,
} from '@/lib/space-runtime';

type SpaceOperation = 'start' | 'stop';
type ActionFeedbackCopy =
  | { type: 'startAccepted' }
  | { type: 'stopAccepted' }
  | { type: 'stopPaused' }
  | { type: 'httpError'; action: SpaceOperation; statusCode: number }
  | { type: 'timeout' }
  | { type: 'connection' };
type RuntimeFeedbackCopy =
  | { type: 'ready' }
  | { type: 'failure'; phase: 'failed' | 'error'; cause: string | null }
  | { type: 'stopped' };
type OperationFeedback = {
  source: 'action' | 'runtime';
  kind: 'success' | 'error';
  message: string;
  durationMs?: number;
  eventKey: string;
  action?: SpaceOperation;
  copy?: ActionFeedbackCopy;
  runtimeCopy?: RuntimeFeedbackCopy;
};

const SPACE_FEEDBACK_SUCCESS_TIMEOUT_MS = 6_000;

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
  const localeRef = useRef(locale);
  localeRef.current = locale;
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
  const feedbackEventRef = useRef<string | null>(null);
  const runtimeFeedbackEventRef = useRef<string | null>(null);
  const feedbackClearRef = useRef<number | null>(null);
  const actionControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  const actionEpochRef = useRef(0);
  const runtimeCycleRef = useRef(0);
  const lastActionRef = useRef<SpaceOperation | null>(null);
  const lastActionEpochRef = useRef<number | null>(null);
  const stopTerminalEpochRef = useRef<number | null>(null);
  const previousPhaseRef = useRef<SpaceRuntimePhase>('checking');

  const controlBase = `/api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  const runUrl = `/run/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/`;
  const displayName = repo
    .replace(/-space$/i, '')
    .split(/[-_]+/)
    .map((part) => part.toLowerCase() === 'ocr' ? 'OCR' : part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

  const phase = runtime?.phase || 'checking';

  function showFeedback(next: OperationFeedback) {
    if (feedbackEventRef.current === next.eventKey) return;
    feedbackEventRef.current = next.eventKey;
    if (feedbackClearRef.current !== null) {
      window.clearTimeout(feedbackClearRef.current);
      feedbackClearRef.current = null;
    }
    setFeedback(next);
    if (next.kind === 'success') {
      feedbackClearRef.current = window.setTimeout(() => {
        setFeedback((current) => current?.eventKey === next.eventKey ? null : current);
        feedbackClearRef.current = null;
      }, SPACE_FEEDBACK_SUCCESS_TIMEOUT_MS);
    }
  }

  function showRuntimeFeedback(next: OperationFeedback) {
    if (runtimeFeedbackEventRef.current === next.eventKey) return;
    runtimeFeedbackEventRef.current = next.eventKey;
    showFeedback(next);
  }

  function actionFeedbackMessage(copy: ActionFeedbackCopy): string {
    switch (copy.type) {
      case 'startAccepted':
        return ui(localeRef.current, '起動要求を受け付けました。', 'Start request accepted.');
      case 'stopAccepted':
        return ui(localeRef.current, '停止要求を受け付けました。Spaceを停止中です。', 'Stop request accepted. Space is stopping.');
      case 'stopPaused':
        return ui(localeRef.current, 'Spaceを一時停止しました。', 'Space paused.');
      case 'httpError':
        return actionError(copy.action, copy.statusCode);
      case 'timeout':
        return ui(localeRef.current, '操作が30秒でタイムアウトしました。状態を確認してから再度お試しください。', 'The operation timed out after 30 seconds. Check the status before retrying.');
      case 'connection':
        return ui(localeRef.current, 'Space Runnerに接続できませんでした。', 'Could not connect to spaces-runner.');
    }
  }

  function runtimeFeedbackMessage(copy: RuntimeFeedbackCopy): string {
    switch (copy.type) {
      case 'ready':
        return ui(localeRef.current, 'Spaceの起動が完了しました。アプリを操作できます。', 'Space is ready. You can use the app now.');
      case 'failure':
        return copy.cause
          ? ui(localeRef.current, `原因: ${copy.cause}。状態を確認してから「もう一度起動」を選んでください。`, `Cause: ${copy.cause}. Check the state, then choose “Try starting again.”`)
          : ui(localeRef.current, 'ランナーが起動失敗を返しました。状態を確認してから「もう一度起動」を選んでください。', 'The runner reported a startup failure. Check the state, then choose “Try starting again.”');
      case 'stopped':
        return ui(localeRef.current, 'Spaceを一時停止しました。', 'Space paused.');
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      actionControllerRef.current?.abort('unmount');
      if (feedbackClearRef.current !== null) window.clearTimeout(feedbackClearRef.current);
    };
  }, []);

  useEffect(() => {
    const previousPhase = previousPhaseRef.current;
    const phaseChanged = previousPhase !== phase;
    if (phaseChanged) {
      if (previousPhase === 'running' && phase !== 'running') runtimeCycleRef.current += 1;
      previousPhaseRef.current = phase;
    }
    const eventPrefix = `runtime:${runtimeCycleRef.current}`;
    const actionErrorVisible = feedback?.source === 'action' && feedback.kind === 'error';
    const previousWasFailure = previousPhase === 'failed' || previousPhase === 'error';
    const runtimeIsFailure = phase === 'failed' || phase === 'error';
    const runtimeRecovered = phaseChanged
      && previousWasFailure
      && !runtimeIsFailure
      && (phase !== 'running' || iframePhase === 'ready');
    const leftRunning = phaseChanged && previousPhase === 'running' && phase !== 'running';
    const confirmedRecovery = actionErrorVisible && (
      (feedback.action === 'start' && phase === 'running' && iframePhase === 'ready')
      || (feedback.action === 'stop' && phase === 'stopped')
    );
    if (runtimeRecovered) {
      feedbackEventRef.current = null;
      runtimeFeedbackEventRef.current = null;
    }
    if (feedback?.source === 'runtime' && (runtimeRecovered || leftRunning)) {
      feedbackEventRef.current = null;
      runtimeFeedbackEventRef.current = null;
      setFeedback(null);
    }
    if (actionErrorVisible && confirmedRecovery) {
      feedbackEventRef.current = null;
      runtimeFeedbackEventRef.current = null;
      setFeedback(null);
    }
    if (actionErrorVisible && !confirmedRecovery) return;
    if (phase === 'running' && iframePhase === 'ready') {
      const runtimeCopy: RuntimeFeedbackCopy = { type: 'ready' };
      showRuntimeFeedback({
        source: 'runtime',
        kind: 'success',
        eventKey: `${eventPrefix}:${runtimeCopy.type}:running`,
        message: runtimeFeedbackMessage(runtimeCopy),
        runtimeCopy,
      });
    } else if (phase === 'failed' || phase === 'error') {
      const runtimeCopy: RuntimeFeedbackCopy = { type: 'failure', phase, cause: runtime?.runtimeError || null };
      showRuntimeFeedback({
        source: 'runtime',
        kind: 'error',
        eventKey: `${eventPrefix}:${runtimeCopy.type}:${runtimeCopy.phase}:${runtimeCopy.cause || 'generic'}`,
        message: runtimeFeedbackMessage(runtimeCopy),
        runtimeCopy,
      });
    } else if (phase === 'stopped' && phaseChanged && lastActionRef.current === 'stop') {
      const stopEpoch = lastActionEpochRef.current;
      if (stopEpoch === null || stopTerminalEpochRef.current === stopEpoch) return;
      const runtimeCopy: RuntimeFeedbackCopy = { type: 'stopped' };
      stopTerminalEpochRef.current = stopEpoch;
      showRuntimeFeedback({
        source: 'runtime',
        kind: 'success',
        eventKey: `${eventPrefix}:stopped:${stopEpoch}`,
        message: runtimeFeedbackMessage(runtimeCopy),
        runtimeCopy,
      });
      lastActionRef.current = null;
      lastActionEpochRef.current = null;
    }
  }, [feedback?.action, feedback?.kind, feedback?.source, iframePhase, locale, phase, runtime?.runtimeError]);

  useEffect(() => {
    setFeedback((current) => {
      if (current?.source === 'action' && current.copy) {
        const message = actionFeedbackMessage(current.copy);
        return current.message === message ? current : { ...current, message };
      }
      if (current?.source !== 'runtime' || !current.runtimeCopy) return current;
      const message = runtimeFeedbackMessage(current.runtimeCopy);
      return current.message === message ? current : { ...current, message };
    });
  }, [locale]);

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
      return ui(localeRef.current, 'Forgejoにログインして再度お試しください。', 'Sign in to Forgejo, then try again.');
    }
    if (statusCode === 403) {
      return ui(localeRef.current, 'このSpaceへの書き込み権限が必要です。', 'Write permission on this Space is required.');
    }
    return action === 'start'
      ? ui(localeRef.current, `Spaceの起動に失敗しました (HTTP ${statusCode})`, `Failed to start this Space (HTTP ${statusCode})`)
      : ui(localeRef.current, `Spaceの一時停止に失敗しました (HTTP ${statusCode})`, `Failed to pause this Space (HTTP ${statusCode})`);
  }

  async function runAction(action: SpaceOperation) {
    if (busy) return;
    setBusy(true);
    setOperation(action);
    setErrorMsg(null);
    const startedAt = performance.now();
    actionEpochRef.current += 1;
    const actionEpoch = actionEpochRef.current;
    lastActionRef.current = action;
    lastActionEpochRef.current = actionEpoch;
    if (action === 'stop') stopTerminalEpochRef.current = null;
    const actionEventKey = `action:${action}:${actionEpoch}`;
    const controller = new AbortController();
    actionControllerRef.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    try {
      const res = await fetch(`${controlBase}/${action}`, {
        method: 'POST',
        signal: controller.signal,
      });
      if (!mountedRef.current) return;
      const durationMs = responseDuration(res, startedAt);
      if (!res.ok) {
        const copy: ActionFeedbackCopy = { type: 'httpError', action, statusCode: res.status };
        const message = actionFeedbackMessage(copy);
        if (action === 'stop') {
          lastActionRef.current = null;
          lastActionEpochRef.current = null;
        }
        setErrorMsg(message);
        showFeedback({ source: 'action', action, copy, kind: 'error', message, durationMs, eventKey: `${actionEventKey}:error:${res.status}` });
        return;
      }
      const json = (await res.json().catch(() => null)) as Record<string, unknown> | null;
      if (!mountedRef.current) return;
      const nextRuntime = json
        ? runtime?.applyPayload(json)
        : await runtime?.refresh();
      if (!mountedRef.current) return;
      const stopTerminalAlreadyShown = action === 'stop'
        && nextRuntime?.phase === 'stopped'
        && stopTerminalEpochRef.current === actionEpoch;
      if (action === 'stop' && nextRuntime?.phase === 'stopped') {
        if (!stopTerminalAlreadyShown) stopTerminalEpochRef.current = actionEpoch;
        lastActionRef.current = null;
        lastActionEpochRef.current = null;
      }
      if (stopTerminalAlreadyShown) return;
      const copy: ActionFeedbackCopy = action === 'start'
        ? { type: 'startAccepted' }
        : nextRuntime?.phase === 'stopped'
          ? { type: 'stopPaused' }
          : { type: 'stopAccepted' };
      const message = actionFeedbackMessage(copy);
      const sameActionErrorVisible = feedback?.source === 'action'
        && feedback.kind === 'error'
        && feedback.action === action;
      if (!sameActionErrorVisible) {
        showFeedback({ source: 'action', action, copy, kind: 'success', message, durationMs, eventKey: `${actionEventKey}:accepted` });
      }
    } catch (error) {
      if (!mountedRef.current) return;
      if (action === 'stop') {
        lastActionRef.current = null;
        lastActionEpochRef.current = null;
      }
      const copy: ActionFeedbackCopy = error instanceof DOMException && error.name === 'AbortError'
        ? { type: 'timeout' }
        : { type: 'connection' };
      const message = actionFeedbackMessage(copy);
      setErrorMsg(message);
      showFeedback({
        source: 'action',
        action,
        copy,
        kind: 'error',
        message,
        durationMs: Math.round(performance.now() - startedAt),
        eventKey: `${actionEventKey}:error:${copy.type}`,
      });
    } finally {
      window.clearTimeout(timeout);
      if (actionControllerRef.current === controller) actionControllerRef.current = null;
      if (mountedRef.current) {
        setBusy(false);
        setOperation(null);
      }
    }
  }

  async function start() {
    await runAction('start');
  }

  async function stop() {
    await runAction('stop');
  }

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

  const runtimeState = getSpaceRuntimeState(phase);
  const stateCopy: Record<SpaceRuntimeStateKind, {
    title: string;
    description: string;
    nextTitle: string;
    nextDescription: string;
  }> = {
    checking: {
      title: ui(locale, 'ワーカーの状態を確認中', 'Checking worker availability'),
      description: ui(locale, '最新の状態を取得しています。起動できるか確認できるまでお待ちください。', 'Fetching the latest state. Wait until we know whether this Space can start.'),
      nextTitle: ui(locale, '確認が終わるまで待機', 'Wait for the check'),
      nextDescription: ui(locale, '状態を確認したあと、起動できる場合だけ起動ボタンを表示します。', 'The start action appears only after the runtime state is confirmed.'),
    },
    available: {
      title: ui(locale, '起動できます', 'Ready to start'),
      description: ui(locale, 'ワーカーは利用可能です。起動すると、キューと準備の状態を追跡します。', 'The worker is available. Starting the Space will show queue and preparation states.'),
      nextTitle: ui(locale, '次の操作', 'Next action'),
      nextDescription: ui(locale, '起動ボタンでSpaceの起動要求を送信します。', 'Use the start action to send a request for this Space.'),
    },
    unavailable: {
      title: ui(locale, 'ワーカーに接続できません', 'Worker unavailable'),
      description: ui(locale, '状態を取得できないため、起動操作をいったん止めています。', 'The runtime state is unavailable, so starting is paused for now.'),
      nextTitle: ui(locale, '状態を再確認', 'Check the state again'),
      nextDescription: ui(locale, '接続が戻り、起動可能だと確認できてから操作してください。', 'Retry the status check before starting when the connection is back.'),
    },
    queued: {
      title: ui(locale, 'キューで待機中', 'Waiting in queue'),
      description: ui(locale, '起動要求は受け付けられました。ワーカーの割り当てを待っています。', 'The start request was accepted. Waiting for a worker assignment.'),
      nextTitle: ui(locale, '次の段階: 準備', 'Next: preparation'),
      nextDescription: ui(locale, 'キューを抜けると、ビルドと起動準備へ進みます。推定時間は表示しません。', 'After the queue, the Space moves into build and startup preparation. No guessed wait time is shown.'),
    },
    preparing: {
      title: ui(locale, 'ワーカーを準備中', 'Preparing the worker'),
      description: ui(locale, 'Spaceのビルドまたは起動を進めています。', 'The Space is being built or started.'),
      nextTitle: ui(locale, '次の段階: アプリ接続', 'Next: connect to the app'),
      nextDescription: ui(locale, '準備が終わると、アプリの接続確認へ進みます。', 'When preparation finishes, the app connection check begins.'),
    },
    running: {
      title: ui(locale, 'アプリを実行中', 'App is running'),
      description: ui(locale, 'アプリの画面を読み込んでいます。', 'The app is available and its screen is loading.'),
      nextTitle: ui(locale, '現在の段階', 'Current stage'),
      nextDescription: ui(locale, 'アプリの操作を開始できます。', 'You can start using the app.'),
    },
    stopping: {
      title: ui(locale, '停止処理を確認中', 'Finishing shutdown'),
      description: ui(locale, 'Spaceの停止が完了するまで、新しい起動要求は送信できません。', 'A new start request is disabled until the Space has finished stopping.'),
      nextTitle: ui(locale, '次の段階: 起動可能', 'Next: ready to start'),
      nextDescription: ui(locale, '停止完了後に起動ボタンを再び表示します。', 'The start action returns after shutdown is complete.'),
    },
    failed: {
      title: ui(locale, '起動に失敗しました', 'Startup failed'),
      description: ui(locale, 'ランナーが失敗を返しました。原因を確認してから、もう一度起動できます。', 'The runner reported a failure. Check the state, then try starting again.'),
      nextTitle: ui(locale, '次の操作', 'Next action'),
      nextDescription: ui(locale, '再試行で新しい起動要求を送信します。前の処理を自動で繰り返しません。', 'Retry sends a new start request; the previous operation is not repeated automatically.'),
    },
    error: {
      title: ui(locale, '起動に失敗しました', 'Startup failed'),
      description: ui(locale, 'ランナーがエラーを返しました。原因を確認してから、もう一度起動できます。', 'The runner reported an error. Check the cause, then try starting again.'),
      nextTitle: ui(locale, 'もう一度起動', 'Try starting again'),
      nextDescription: ui(locale, '再試行で新しい起動要求を送信します。前の処理を自動で繰り返しません。', 'Retry sends a new start request; the previous operation is not repeated automatically.'),
    },
  };
  const copy = stateCopy[runtimeState.kind];
  const stepLabels: Record<SpaceRuntimeStep, string> = {
    availability: ui(locale, '利用可否', 'Availability'),
    queue: ui(locale, 'キュー', 'Queue'),
    prepare: ui(locale, '準備', 'Prepare'),
    app: ui(locale, 'アプリ', 'App'),
  };
  const stepOrder: SpaceRuntimeStep[] = ['availability', 'queue', 'prepare', 'app'];
  const currentStepIndex = stepOrder.indexOf(runtimeState.currentStep);
  const stateIsError = ['unavailable', 'failed', 'error'].includes(runtimeState.kind);
  const stateRole = ['failed', 'error'].includes(runtimeState.kind) ? 'status' : stateIsError ? 'alert' : 'status';
  const stateLive = stateRole === 'alert' ? 'assertive' : stateIsError ? 'off' : 'polite';
  const stateTone: Record<SpaceRuntimeStateKind, string> = {
    checking: 'border-sky-300/30 bg-sky-300/10 text-sky-100',
    available: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100',
    unavailable: 'border-rose-300/30 bg-rose-300/10 text-rose-100',
    queued: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
    preparing: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
    running: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100',
    stopping: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
    failed: 'border-rose-300/30 bg-rose-300/10 text-rose-100',
    error: 'border-rose-300/30 bg-rose-300/10 text-rose-100',
  };
  const statusRetry = runtimeState.kind === 'unavailable'
    || (runtimeState.kind === 'failed' && Boolean(runtime?.error));
  const retryStart = runtimeState.canRetryStart && !statusRetry;
  const stepStatus = (index: number) => {
    if (stateIsError && index === currentStepIndex) return 'blocked';
    if (index < currentStepIndex) return 'complete';
    if (index === currentStepIndex) return 'current';
    return 'upcoming';
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
          {auth.status === 'authenticated' ? (
            <button
              type="button"
              onClick={stop}
              disabled={busy || phase === 'stopped'}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-zinc-300 px-3 text-sm font-medium hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              <HfIcon
                name={operation === 'stop' ? 'spinner' : 'pause'}
                className={`h-3.5 w-3.5 ${operation === 'stop' ? 'motion-safe:animate-spin motion-reduce:animate-none' : ''}`}
              />
              {operation === 'stop' ? ui(locale, '一時停止中…', 'Pausing…') : ui(locale, '一時停止', 'Pause')}
            </button>
          ) : null}
        </div>
      </div>

      {feedback && (
        <div
          role={feedback.kind === 'error' ? 'alert' : 'status'}
          aria-live={feedback.kind === 'error' ? 'assertive' : 'polite'}
          aria-atomic="true"
          data-feedback-kind={feedback.kind}
          data-feedback-event={feedback.eventKey}
          className={`mx-4 mt-3 flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${
            feedback.kind === 'error'
              ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
              : 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
          }`}
        >
          <span className="min-w-0 [overflow-wrap:anywhere]">{feedback.message}</span>
          <span className="flex shrink-0 items-center gap-2">
            {feedback.durationMs !== undefined ? <span className="font-mono text-xs opacity-75">{feedback.durationMs} ms</span> : null}
            <button
              type="button"
              aria-label={ui(locale, '通知を閉じる', 'Dismiss notification')}
              onClick={() => setFeedback(null)}
              className="rounded p-1 text-current/70 hover:bg-black/5 hover:text-current focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-current dark:hover:bg-white/10"
            >
              <span aria-hidden="true">×</span>
            </button>
          </span>
        </div>
      )}

      {errorMsg && <span className="sr-only">{errorMsg}</span>}

      {phase === 'running' ? (
        <div className="nyankoface-space-frame-stage relative">
          {iframeSourceReady ? <iframe
            key={iframeAttempt}
            src={runUrl}
            className={`nyankoface-space-frame w-full border-0 transition-opacity duration-300 motion-reduce:transition-none ${iframePhase === 'ready' ? 'opacity-100' : 'opacity-0'}`}
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
            <div className="nyankoface-space-stage absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#090b12] px-6 text-center text-zinc-300" role={iframePhase === 'error' || iframePhase === 'timeout' ? 'alert' : 'status'} aria-live={iframePhase === 'error' || iframePhase === 'timeout' ? 'assertive' : 'polite'} aria-atomic="true">
              <HfIcon name={iframePhase === 'idle' || iframePhase === 'loading' ? 'spinner' : 'fire'} className={`h-8 w-8 text-violet-300 ${iframePhase === 'idle' || iframePhase === 'loading' ? 'motion-safe:animate-spin motion-reduce:animate-none' : ''}`} />
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
        <div
          className="nyankoface-space-stage relative flex min-h-[calc(100vh-50px)] flex-col overflow-hidden bg-[#090b12] px-4 py-5 text-zinc-400 sm:px-7 sm:py-6"
          data-runtime-state-kind={runtimeState.kind}
          data-runtime-motion={runtimeState.isProgressing ? 'progress' : 'quiet'}
        >
          <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(119,99,255,0.12),transparent_42%),linear-gradient(90deg,rgba(255,255,255,0.025)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:auto,18px_18px,18px_18px]" />
          <div className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col">
            <div className="flex flex-col gap-5 border-b border-white/10 pb-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-zinc-500">
                  {ui(locale, 'Space Runner', 'Space Runner')} · {owner}/{repo}
                </p>
                <h2 className="mt-2 max-w-2xl truncate text-2xl font-bold leading-tight text-zinc-100 sm:text-3xl">
                  {displayName}
                </h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400 sm:text-base">
                  {description || ui(locale, `${owner}/${repo}として公開されたAIアプリです。`, `AI application published as ${owner}/${repo}.`)}
                </p>
              </div>
              <div className="flex shrink-0 gap-2">
                <a
                  href={`/git/${owner}/${repo}/src/branch/main`}
                  aria-label={ui(locale, 'Spaceのファイルを見る', 'View Space files')}
                  title={ui(locale, 'Spaceのファイルを見る', 'View Space files')}
                  className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 bg-white/5 text-zinc-300 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300"
                >
                  <HfIcon name="file" className="h-4 w-4" />
                </a>
                {auth.status === 'authenticated' ? (
                  <a
                    href={`/git/${owner}/${repo}/settings`}
                    aria-label={ui(locale, 'ForgejoでSpaceの設定を開く', 'Open Space settings in Forgejo')}
                    title={ui(locale, 'ForgejoでSpaceの設定を開く', 'Open Space settings in Forgejo')}
                    className="grid h-10 w-10 place-items-center rounded-lg border border-white/10 bg-white/5 text-zinc-300 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300"
                  >
                    <HfIcon name="gear" className="h-4 w-4" />
                  </a>
                ) : null}
              </div>
            </div>

            <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.9fr)]">
              <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4 sm:p-5">
                <div className="flex items-start gap-3">
                  <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl border ${stateTone[runtimeState.kind]} ${runtimeState.isProgressing ? 'motion-safe:animate-pulse' : ''} motion-reduce:animate-none`}>
                    <HfIcon name={stateIsError ? 'warning' : runtimeState.kind === 'available' ? 'play' : 'space'} className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-zinc-500">
                        {statusLabel[phase]}
                      </p>
                      <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] font-semibold text-zinc-500">
                        {execution === 'remote-gpu' ? 'GPU' : 'CPU'}
                      </span>
                    </div>
                    <div role={stateRole} aria-live={stateLive} aria-atomic="true" className="mt-2">
                      <h3 className="text-xl font-bold text-zinc-100">{copy.title}</h3>
                      <p className="mt-1 max-w-xl text-sm leading-6 text-zinc-400">{copy.description}</p>
                    </div>
                  </div>
                </div>

                <div className="mt-6 grid grid-cols-4 gap-2" aria-label={ui(locale, 'Spaceの準備段階', 'Space readiness stages')}>
                  {stepOrder.map((step, index) => {
                    const status = stepStatus(index);
                    return (
                      <div key={step} className="min-w-0">
                        <div className={`mb-2 h-1 rounded-full ${status === 'complete' ? 'bg-emerald-300/70' : status === 'current' ? 'bg-violet-300' : status === 'blocked' ? 'bg-rose-300/75' : 'bg-white/10'}`} />
                        <p className={`truncate text-[11px] font-semibold ${status === 'current' ? 'text-zinc-100' : status === 'blocked' ? 'text-rose-200' : status === 'complete' ? 'text-emerald-200' : 'text-zinc-600'}`}>
                          {stepLabels[step]}
                        </p>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-xs text-zinc-600">
                  {runtimeState.isProgressing
                    ? `${copy.title} · ${formatElapsedDuration(runtime?.elapsedMs || 0)}`
                    : ui(locale, '現在の状態を確認してから操作できます。', 'The current state is shown before you act.')}
                </p>
              </div>

              <div className="flex flex-col justify-between rounded-2xl border border-white/10 bg-[#111421] p-4 sm:p-5">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{copy.nextTitle}</p>
                  <p className="mt-2 text-sm leading-6 text-zinc-300">{copy.nextDescription}</p>
                </div>
                <div className="mt-6">
                  {runtimeState.canStart && !statusRetry ? (
                    <button
                      type="button"
                      onClick={start}
                      disabled={busy}
                      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-violet-300/40 bg-violet-300/15 px-4 py-3 text-sm font-semibold text-violet-100 transition hover:bg-violet-300/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-200 disabled:cursor-wait disabled:opacity-60"
                    >
                      <HfIcon name={operation === 'start' ? 'spinner' : 'play'} className={`h-4 w-4 ${operation === 'start' ? 'motion-safe:animate-spin motion-reduce:animate-none' : ''}`} />
                      {operation === 'start'
                        ? ui(locale, '起動要求を送信中…', 'Sending start request…')
                        : ui(locale, 'Spaceを起動', 'Start this Space')}
                    </button>
                  ) : retryStart ? (
                    <button
                      type="button"
                      onClick={start}
                      disabled={busy}
                      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-violet-300/40 bg-violet-300/15 px-4 py-3 text-sm font-semibold text-violet-100 transition hover:bg-violet-300/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-200 disabled:cursor-wait disabled:opacity-60"
                    >
                      <HfIcon name={operation === 'start' ? 'spinner' : 'play'} className={`h-4 w-4 ${operation === 'start' ? 'motion-safe:animate-spin motion-reduce:animate-none' : ''}`} />
                      {operation === 'start'
                        ? ui(locale, '起動要求を送信中…', 'Sending start request…')
                        : ui(locale, 'もう一度起動', 'Try starting again')}
                    </button>
                  ) : statusRetry ? (
                    <button
                      type="button"
                      onClick={() => void runtime?.refresh()}
                      disabled={runtime?.checking}
                      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/5 px-4 py-3 text-sm font-semibold text-zinc-100 transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-200 disabled:cursor-wait disabled:opacity-60"
                    >
                      <HfIcon name={runtime?.checking ? 'spinner' : 'refresh'} className={`h-4 w-4 ${runtime?.checking ? 'motion-safe:animate-spin motion-reduce:animate-none' : ''}`} />
                      {runtime?.checking ? ui(locale, '再確認中…', 'Checking…') : ui(locale, '状態を再確認', 'Check the state again')}
                    </button>
                  ) : (
                    <div className="flex min-h-11 items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-zinc-400" role="status" aria-live="polite">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${runtimeState.isProgressing ? 'bg-amber-300 motion-safe:animate-pulse motion-reduce:animate-none' : 'bg-zinc-600'}`} />
                      <span>{runtimeState.isProgressing ? ui(locale, 'このまま待機してください。', 'Please wait here.') : ui(locale, '現在は操作を受け付けていません。', 'No action is available right now.')}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-auto pt-6 text-center text-xs text-zinc-600">
              {ui(locale, '提供', 'Powered by')} {owner}/{repo} · NyankoFace Runner
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
