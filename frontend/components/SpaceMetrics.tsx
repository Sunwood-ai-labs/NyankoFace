'use client';

import { useEffect, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ensureBrowserView, type BrowserViewMetrics } from '@/lib/browser-metrics';
import { ui } from '@/lib/i18n';

export default function SpaceMetrics({
  owner,
  repo,
  forgejoHref,
}: {
  owner: string;
  repo: string;
  forgejoHref: string;
}) {
  const { locale } = useLocale();
  const [metrics, setMetrics] = useState<BrowserViewMetrics | null>(null);
  const [state, setState] = useState<'loading' | 'available' | 'error'>('loading');

  useEffect(() => {
    let active = true;
    setState('loading');
    void ensureBrowserView(owner, repo).then((nextMetrics) => {
        if (!active) return;
        if (nextMetrics) {
          setMetrics(nextMetrics);
          setState('available');
        } else {
          setState('error');
        }
      });
    return () => { active = false; };
  }, [owner, repo]);

  const loading = state === 'loading';
  return (
    <>
      <a
        href={forgejoHref}
        title={state === 'available'
          ? ui(locale, `記録済みいいね ${metrics?.likes ?? 0}件`, `${metrics?.likes ?? 0} recorded likes`)
          : ui(locale, 'いいね数を取得できません', 'Like count is unavailable')}
        className="ml-2 inline-flex h-8 items-center gap-1 rounded-lg border border-zinc-200 px-2.5 text-xs text-zinc-500 hover:bg-zinc-50"
        data-metric-state={state}
      >
        <HfIcon name="heart" className={`h-3 w-3 ${loading ? 'animate-pulse' : ''}`} />
        {state === 'available'
          ? ui(locale, `${metrics?.likes ?? 0} いいね`, `${metrics?.likes ?? 0} likes`)
          : ui(locale, '— いいね', '— likes')}
      </a>
      <span
        className="inline-flex h-8 items-center rounded-lg border border-zinc-100 px-2.5 text-xs text-zinc-500"
        title={state === 'available'
          ? ui(locale, `実閲覧数 ${metrics?.views ?? 0}回`, `${metrics?.views ?? 0} recorded views`)
          : ui(locale, '閲覧数を取得できません', 'Recorded views are unavailable')}
        data-metric-state={state}
      >
        <HfIcon name="eye" className={`mr-1 h-3 w-3 ${loading ? 'animate-pulse' : ''}`} />
        {state === 'available' ? metrics?.views ?? 0 : '—'}
      </span>
    </>
  );
}
