'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  normalizeSpaceRuntime,
  SPACE_STATUS_TIMEOUT_MS,
  spaceRuntimePollInterval,
  type SpaceRuntimeInfo,
  type SpaceRuntimePhase,
} from '@/lib/space-runtime';

type RuntimePayload = Record<string, unknown> | null;

type SpaceRuntimeContextValue = SpaceRuntimeInfo & {
  checking: boolean;
  error: string | null;
  elapsedMs: number;
  requestDurationMs: number | null;
  refresh: () => Promise<SpaceRuntimeInfo | null>;
  applyPayload: (payload: RuntimePayload) => SpaceRuntimeInfo;
};

const SpaceRuntimeContext = createContext<SpaceRuntimeContextValue | null>(null);

export function useSpaceRuntime() {
  return useContext(SpaceRuntimeContext);
}

export default function SpaceRuntimeProvider({
  owner,
  repo,
  children,
}: {
  owner: string;
  repo: string;
  children: React.ReactNode;
}) {
  const [runtime, setRuntime] = useState<SpaceRuntimeInfo>({
    status: 'stopped',
    phase: 'checking',
    execution: 'local-cpu',
  });
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [requestDurationMs, setRequestDurationMs] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [pollRevision, setPollRevision] = useState(0);
  const requestRef = useRef<AbortController | null>(null);
  const requestRevisionRef = useRef(0);
  const phaseStartedAtRef = useRef(performance.now());
  const phaseRef = useRef<SpaceRuntimePhase>('checking');
  const base = `/runner-api/spaces/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;

  const commitPayload = useCallback((payload: RuntimePayload) => {
    const next = normalizeSpaceRuntime(payload);
    if (phaseRef.current !== next.phase) {
      phaseRef.current = next.phase;
      phaseStartedAtRef.current = performance.now();
      setElapsedMs(0);
    }
    setRuntime(next);
    setError(null);
    return next;
  }, []);

  const applyPayload = useCallback((payload: RuntimePayload) => {
    requestRevisionRef.current += 1;
    requestRef.current?.abort('action-response');
    requestRef.current = null;
    setChecking(false);
    const next = commitPayload(payload);
    setPollRevision((revision) => revision + 1);
    return next;
  }, [commitPayload]);

  const refresh = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    const requestRevision = requestRevisionRef.current + 1;
    requestRevisionRef.current = requestRevision;
    requestRef.current = controller;
    const startedAt = performance.now();
    const timeout = window.setTimeout(() => controller.abort('timeout'), SPACE_STATUS_TIMEOUT_MS);
    setChecking(true);
    try {
      const response = await fetch(`${base}/status`, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json().catch(() => null) as RuntimePayload;
      if (
        requestRevisionRef.current !== requestRevision
        || requestRef.current !== controller
      ) return null;
      const next = commitPayload(payload);
      setRequestDurationMs(Math.round(performance.now() - startedAt));
      return next;
    } catch (reason) {
      if (requestRevisionRef.current !== requestRevision) return null;
      if (controller.signal.aborted && controller.signal.reason !== 'timeout') return null;
      const message = controller.signal.reason === 'timeout'
        ? 'Runtime status timed out.'
        : reason instanceof Error ? reason.message : 'Runtime status is unavailable.';
      if (phaseRef.current !== 'offline') {
        phaseRef.current = 'offline';
        phaseStartedAtRef.current = performance.now();
        setElapsedMs(0);
      }
      setRuntime((current) => ({ ...current, status: 'unavailable', phase: 'offline' }));
      setError(message);
      setRequestDurationMs(Math.round(performance.now() - startedAt));
      return null;
    } finally {
      window.clearTimeout(timeout);
      if (requestRef.current === controller) {
        requestRef.current = null;
        setChecking(false);
        setPollRevision((revision) => revision + 1);
      }
    }
  }, [base, commitPayload]);

  useEffect(() => {
    const delay = pollRevision === 0 ? 0 : spaceRuntimePollInterval(runtime.phase);
    const timer = window.setTimeout(() => void refresh(), delay);
    return () => window.clearTimeout(timer);
  }, [pollRevision, refresh, runtime.phase]);

  useEffect(() => () => requestRef.current?.abort('source-change'), [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsedMs(Math.round(performance.now() - phaseStartedAtRef.current));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const value = useMemo<SpaceRuntimeContextValue>(() => ({
    ...runtime,
    checking,
    error,
    elapsedMs,
    requestDurationMs,
    refresh,
    applyPayload,
  }), [applyPayload, checking, elapsedMs, error, refresh, requestDurationMs, runtime]);

  return <SpaceRuntimeContext.Provider value={value}>{children}</SpaceRuntimeContext.Provider>;
}
