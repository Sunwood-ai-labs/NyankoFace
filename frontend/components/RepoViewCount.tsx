'use client';

import { useEffect, useState } from 'react';
import HfIcon from '@/components/HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

type ViewResponse = {
  metrics?: { views?: number };
};

export default function RepoViewCount({
  owner,
  repo,
  initialViews,
  initialAvailable,
}: {
  owner: string;
  repo: string;
  initialViews: number;
  initialAvailable: boolean;
}) {
  const [views, setViews] = useState(initialViews);
  const [state, setState] = useState<'available' | 'loading' | 'error'>(initialAvailable ? 'available' : 'loading');
  const { locale } = useLocale();

  useEffect(() => {
    // performance.timeOrigin is stable for this document (including React
    // remounts) and changes on the next navigation/reload. That gives us one
    // count per real page load without Strict Mode double-counting.
    const idempotencyKey = `browser:${owner}/${repo}:${performance.timeOrigin}`;

    const controller = new AbortController();
    setState('loading');
    fetch(`/runner-api/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/views`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      signal: controller.signal,
    })
      .then((response) => response.ok ? response.json() as Promise<ViewResponse> : null)
      .then((result) => {
        const nextViews = result?.metrics?.views;
        if (typeof nextViews === 'number') {
          setViews(nextViews);
          setState('available');
        } else {
          setState('error');
        }
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          console.warn('Could not record Space view', error);
          setState('error');
        }
      });

    return () => controller.abort();
  }, [owner, repo]);

  return (
    <span
      className="inline-flex h-8 items-center rounded-lg border border-zinc-100 px-2.5 text-xs text-zinc-500"
      title={state === 'available'
        ? ui(locale, `実閲覧数 ${views}回`, `${views} recorded views`)
        : state === 'loading'
          ? ui(locale, '閲覧数を集計中です', 'Loading recorded views')
          : ui(locale, '閲覧数を取得できませんでした', 'Recorded views are unavailable')}
      aria-label={state === 'available'
        ? ui(locale, `実閲覧数 ${views}回`, `${views} recorded views`)
        : state === 'loading'
          ? ui(locale, '閲覧数を集計中です', 'Loading recorded views')
          : ui(locale, '閲覧数を取得できませんでした', 'Recorded views are unavailable')}
      data-metric-state={state}
    >
      <HfIcon name="eye" className={`mr-1 h-3 w-3 ${state === 'loading' ? 'animate-pulse' : ''}`} />
      {state === 'available' ? views : '—'}
    </span>
  );
}
