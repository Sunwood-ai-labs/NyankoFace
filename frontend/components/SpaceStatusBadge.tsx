'use client';

import { useContext, useEffect, useState } from 'react';
import type { SpaceExecution, SpaceStatus, SpaceStatusInfo } from '@/lib/space-status';
import { SpaceStatusContext } from './SpaceStatusProvider';
import { useSpaceRuntime } from './SpaceRuntimeProvider';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';
import type { SpaceRuntimePhase } from '@/lib/space-runtime';

export default function SpaceStatusBadge({
  owner,
  repo,
  variant = 'card',
}: {
  owner: string;
  repo: string;
  variant?: 'card' | 'header';
}) {
  const { locale } = useLocale();
  const stateLabels: Record<SpaceRuntimePhase, string> = {
    checking: ui(locale, '状態を確認中', 'Checking runtime'),
    queued: ui(locale, '待機中', 'Queued'),
    leased: ui(locale, '割当済み', 'Leased'),
    building: ui(locale, 'ビルド中', 'Building'),
    starting: ui(locale, '起動中', 'Starting'),
    warming: ui(locale, '準備中', 'Warming up'),
    running: ui(locale, '実行中', 'Running'),
    stopping: ui(locale, '停止中', 'Stopping'),
    stopped: ui(locale, 'オンデマンド', 'On demand'),
    offline: ui(locale, 'オフライン', 'Offline'),
    unavailable: ui(locale, '利用不可', 'Unavailable'),
    failed: ui(locale, '失敗', 'Failed'),
    error: ui(locale, 'エラー', 'Error'),
  };
  const detailRuntime = useSpaceRuntime();
  const directoryStatuses = useContext(SpaceStatusContext);
  const directoryStatus = directoryStatuses?.[`${owner}/${repo}`];
  const [detailInfo, setDetailInfo] = useState<SpaceStatusInfo>({
    status: 'stopped',
    execution: 'local-cpu',
  });
  const info = detailRuntime || (directoryStatuses
    ? (directoryStatus || { status: 'stopped', execution: 'local-cpu' as SpaceExecution })
    : detailInfo);
  const { status, execution } = info;
  const phase: SpaceRuntimePhase = detailRuntime?.phase || status;

  useEffect(() => {
    if (detailRuntime || directoryStatuses) return;
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`/runner-api/spaces/${owner}/${repo}/status`, {
          cache: 'no-store',
        });
        const data = (await response.json()) as {
          status?: SpaceStatus;
          execution?: SpaceExecution;
        };
        if (active && data.status && data.status in stateLabels) {
          setDetailInfo({
            status: data.status,
            execution: data.execution || 'local-cpu',
          });
        }
      } catch {
        if (active) setDetailInfo((current) => ({ ...current, status: 'error' }));
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [detailRuntime, directoryStatuses, owner, repo]);

  const className = variant === 'header'
    ? phase === 'running'
      ? 'space-status-header space-status-header--running inline-flex h-8 items-center rounded-lg border border-emerald-100 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700'
      : ['checking', 'building', 'queued', 'leased', 'starting', 'warming', 'stopping'].includes(phase)
        ? 'space-status-header space-status-header--building inline-flex h-8 items-center rounded-lg border border-amber-100 bg-amber-50 px-3 text-xs font-semibold text-amber-700'
        : ['error', 'failed', 'unavailable', 'offline'].includes(phase)
          ? 'space-status-header space-status-header--error inline-flex h-8 items-center rounded-lg border border-red-100 bg-red-50 px-3 text-xs font-semibold text-red-700'
          : 'space-status-header space-status-header--stopped inline-flex h-8 items-center rounded-lg border border-zinc-200 bg-zinc-100 px-3 text-xs font-semibold text-zinc-600'
    : 'rounded bg-white/15 px-1.5 py-1 shadow-sm ring-1 ring-white/10 backdrop-blur';

  return (
    <span
      className={className}
      aria-live="polite"
      data-runtime-phase={phase}
      data-runtime-request-ms={detailRuntime?.requestDurationMs ?? undefined}
    >
      {execution === 'remote-gpu' ? 'GPU' : 'CPU'} · {stateLabels[phase]}
    </span>
  );
}
