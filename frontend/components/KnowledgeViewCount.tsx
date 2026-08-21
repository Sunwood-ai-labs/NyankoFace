'use client';

import { useEffect, useState } from 'react';
import HfIcon from '@/components/HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';
import { formatCompactCount } from '@/lib/format';

type ViewResponse = {
  metrics?: { views?: number };
};

export default function KnowledgeViewCount({
  owner,
  repo,
  slug,
  initialViews,
  initialAvailable,
  record = false,
}: {
  owner: string;
  repo: string;
  slug: string;
  initialViews: number;
  initialAvailable: boolean;
  record?: boolean;
}) {
  const [views, setViews] = useState(initialViews);
  const [state, setState] = useState<'available' | 'loading' | 'error'>(initialAvailable ? 'available' : record ? 'loading' : 'error');
  const { locale } = useLocale();
  const compactViews = formatCompactCount(views, locale);

  useEffect(() => {
    if (!record) return;
    const idempotencyKey = `knowledge-browser:${owner}/${repo}/${slug}:${performance.timeOrigin}`;
    const controller = new AbortController();
    setState('loading');
    fetch(`/runner-api/metrics/knowledge/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(slug)}/views`, {
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
          console.warn('Could not record knowledge view', error);
          setState('error');
        }
      });
    return () => controller.abort();
  }, [owner, repo, slug, record]);

  return (
    <span
      className="inline-flex items-center gap-1 whitespace-nowrap"
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
      <HfIcon name="eye" className={`h-3.5 w-3.5 ${state === 'loading' ? 'animate-pulse' : ''}`} />
      {state === 'available' ? ui(locale, `${compactViews} views`, `${compactViews} views`) : '—'}
    </span>
  );
}
