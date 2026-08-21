import type { SpaceExecution, SpaceStatus, SpaceStatusInfo } from './space-status';

export type SpaceRuntimePhase = SpaceStatus | 'checking' | 'starting' | 'warming' | 'offline';
export type SpaceIframePhase = 'idle' | 'loading' | 'ready' | 'timeout' | 'error';
export type SpaceRuntimeStateKind =
  | 'checking'
  | 'available'
  | 'unavailable'
  | 'queued'
  | 'preparing'
  | 'running'
  | 'stopping'
  | 'failed'
  | 'error';
export type SpaceRuntimeStep = 'availability' | 'queue' | 'prepare' | 'app';

export interface SpaceRuntimeState {
  kind: SpaceRuntimeStateKind;
  currentStep: SpaceRuntimeStep;
  nextStep: SpaceRuntimeStep | null;
  isProgressing: boolean;
  canStart: boolean;
  canRetry: boolean;
  canRetryStart: boolean;
}

export interface SpaceRuntimeInfo extends SpaceStatusInfo {
  phase: SpaceRuntimePhase;
}

type RuntimePayload = {
  status?: unknown;
  state?: unknown;
  execution?: unknown;
};

export const SPACE_STATUS_TIMEOUT_MS = 8_000;
export const SPACE_IFRAME_TIMEOUT_MS = 20_000;
export const SPACE_IFRAME_RETRY_DELAY_MS = 750;

export function isSpaceGatewayPending(documentText: string | null | undefined): boolean {
  if (!documentText) return false;
  const normalized = documentText.toLowerCase();
  return normalized.includes('space is not running')
    || normalized.includes('space is still starting')
    || normalized.includes('space is not ready');
}

export function isSpaceGatewayErrorDocument(
  documentText: string | null | undefined,
  contentType: string | null | undefined,
): boolean {
  if (isSpaceGatewayPending(documentText)) return true;
  if (!documentText || !contentType?.toLowerCase().includes('application/json')) return false;
  try {
    const payload = JSON.parse(documentText) as Record<string, unknown> | null;
    return typeof payload?.error === 'string' && payload.error.trim().length > 0;
  } catch {
    return false;
  }
}

export function normalizeSpaceRuntime(payload: RuntimePayload | null): SpaceRuntimeInfo {
  const raw = String(payload?.status ?? payload?.state ?? '').trim().toLowerCase();
  const execution: SpaceExecution = payload?.execution === 'remote-gpu' ? 'remote-gpu' : 'local-cpu';

  if (!raw) return { status: 'error', phase: 'offline', execution };
  if (raw.includes('offline')) return { status: 'unavailable', phase: 'offline', execution };
  if (raw.includes('unavailable')) return { status: 'unavailable', phase: 'unavailable', execution };
  if (raw.includes('fail')) return { status: 'failed', phase: 'failed', execution };
  if (raw.includes('error')) return { status: 'error', phase: 'error', execution };
  if (raw.includes('warming')) return { status: 'leased', phase: 'warming', execution };
  if (raw === 'cancel_requested') return { status: 'stopping', phase: 'stopping', execution };
  if (raw === 'cancelled' || raw === 'canceled') return { status: 'stopped', phase: 'stopped', execution };
  if (raw.includes('start')) return { status: 'leased', phase: 'starting', execution };
  if (raw.includes('queue') || raw.includes('pending')) return { status: 'queued', phase: 'queued', execution };
  if (raw.includes('lease')) return { status: 'leased', phase: 'leased', execution };
  if (raw.includes('build')) return { status: 'building', phase: 'building', execution };
  if (raw.includes('run')) return { status: 'running', phase: 'running', execution };
  if (raw.includes('stopping')) return { status: 'stopping', phase: 'stopping', execution };
  if (raw.includes('stop') || raw.includes('exit') || raw === 'none') {
    return { status: 'stopped', phase: 'stopped', execution };
  }
  return { status: 'error', phase: 'error', execution };
}

export function getSpaceRuntimeState(phase: SpaceRuntimePhase): SpaceRuntimeState {
  if (phase === 'checking') {
    return {
      kind: 'checking',
      currentStep: 'availability',
      nextStep: 'queue',
      isProgressing: true,
      canStart: false,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'stopped') {
    return {
      kind: 'available',
      currentStep: 'availability',
      nextStep: 'queue',
      isProgressing: false,
      canStart: true,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'offline' || phase === 'unavailable') {
    return {
      kind: 'unavailable',
      currentStep: 'availability',
      nextStep: null,
      isProgressing: false,
      canStart: false,
      canRetry: true,
      canRetryStart: false,
    };
  }
  if (phase === 'queued') {
    return {
      kind: 'queued',
      currentStep: 'queue',
      nextStep: 'prepare',
      isProgressing: true,
      canStart: false,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'leased' || phase === 'building' || phase === 'starting' || phase === 'warming') {
    return {
      kind: 'preparing',
      currentStep: 'prepare',
      nextStep: 'app',
      isProgressing: true,
      canStart: false,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'running') {
    return {
      kind: 'running',
      currentStep: 'app',
      nextStep: null,
      isProgressing: false,
      canStart: false,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'stopping') {
    return {
      kind: 'stopping',
      currentStep: 'availability',
      nextStep: 'queue',
      isProgressing: true,
      canStart: false,
      canRetry: false,
      canRetryStart: false,
    };
  }
  if (phase === 'failed') {
    return {
      kind: 'failed',
      currentStep: 'prepare',
      nextStep: 'queue',
      isProgressing: false,
      canStart: false,
      canRetry: true,
      canRetryStart: true,
    };
  }
  return {
    kind: 'error',
    currentStep: 'prepare',
    nextStep: 'queue',
    isProgressing: false,
    canStart: false,
    canRetry: true,
    canRetryStart: true,
  };
}

export function spaceRuntimePollInterval(phase: SpaceRuntimePhase): number {
  if (['queued', 'leased', 'building', 'starting', 'warming', 'stopping'].includes(phase)) return 2_000;
  if (phase === 'running') return 10_000;
  if (phase === 'stopped') return 15_000;
  return 20_000;
}

export function isSpaceRuntimePending(phase: SpaceRuntimePhase): boolean {
  return ['checking', 'queued', 'leased', 'building', 'starting', 'warming', 'stopping'].includes(phase);
}

export function formatElapsedDuration(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1_000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}:${seconds.toString().padStart(2, '0')}` : `${seconds}s`;
}
