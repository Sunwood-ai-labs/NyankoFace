'use client';

import { useEffect, useMemo, useState } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ensureBrowserView } from '@/lib/browser-metrics';
import { ui } from '@/lib/i18n';

type MetricPoint = {
  bucket_start: string;
  views: number;
  downloads: number;
  likes: number;
  likes_delta: number;
  downloads_by_source: { raw: number; lfs: number; automation: number };
};

type MetricSeriesResponse = {
  data_state: 'data' | 'no_data';
  bucket: 'day' | 'week' | 'month';
  timezone: string;
  series: MetricPoint[];
  totals: {
    views: number;
    downloads: number;
    likes: number;
    downloads_by_source: { raw: number; lfs: number; automation: number };
  };
  generated_at?: string | null;
  updated_at?: string | null;
};

type PanelState = 'loading' | 'available' | 'no-data' | 'unavailable';

const chartLines = [
  { key: 'views' as const, color: '#2563eb', label: 'Views', labelJa: '閲覧' },
  { key: 'downloads' as const, color: '#d97706', label: 'Downloads', labelJa: 'ダウンロード' },
  { key: 'likes' as const, color: '#db2777', label: 'Likes', labelJa: 'いいね' },
];

function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale === 'ja' ? 'ja-JP' : 'en-US').format(value);
}

function formatDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleDateString(locale === 'ja' ? 'ja-JP' : 'en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

function formatDateTime(value: string | null | undefined, locale: string): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString(locale === 'ja' ? 'ja-JP' : 'en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'UTC',
  });
}

function linePoints(series: MetricPoint[], key: 'views' | 'downloads' | 'likes', width: number, height: number): string {
  const paddingX = 22;
  const paddingY = 20;
  const max = Math.max(1, ...series.map((point) => point[key]));
  const denominator = Math.max(1, series.length - 1);
  return series.map((point, index) => {
    const x = paddingX + ((width - paddingX * 2) * index) / denominator;
    const y = height - paddingY - ((height - paddingY * 2) * point[key]) / max;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

export default function RepoMetricsPanel({
  owner,
  repo,
  recordView,
}: {
  owner: string;
  repo: string;
  recordView: boolean;
}) {
  const { locale } = useLocale();
  const [state, setState] = useState<PanelState>('loading');
  const [data, setData] = useState<MetricSeriesResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        if (recordView) {
          await ensureBrowserView(owner, repo);
        }
        const response = await fetch(
          `/runner-api/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/timeseries?bucket=day&timezone=UTC`,
          { cache: 'no-store', signal: controller.signal },
        );
        if (!response.ok) throw new Error(`metrics HTTP ${response.status}`);
        const result = await response.json() as MetricSeriesResponse;
        setData(result);
        setState(result.data_state === 'data' ? 'available' : 'no-data');
      } catch (error) {
        if (!controller.signal.aborted) setState('unavailable');
      }
    };
    void load();
    return () => controller.abort();
  }, [owner, repo, recordView]);

  const chart = useMemo(() => {
    if (!data?.series.length) return null;
    const width = 720;
    const height = 190;
    return { width, height };
  }, [data]);

  return (
    <section
      className="nyankoface-repo-metrics mb-7 min-w-0 overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
      data-metric-state={state}
      aria-labelledby="nyankoface-repo-metrics-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
        <div>
          <div className="flex items-center gap-2">
            <HfIcon name="chart" className="h-4 w-4 text-accent-dark" />
            <h2 id="nyankoface-repo-metrics-title" className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
              {ui(locale, '実測アクティビティ', 'Measured activity')}
            </h2>
          </div>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {ui(locale, 'サーバーで成功したイベントをUTCの日別に集計', 'Successful server events, bucketed daily in UTC')}
          </p>
        </div>
        <span className="text-xs text-zinc-400" data-metric-period>
          {data ? `${data.bucket} · ${data.timezone}` : 'day · UTC'}
        </span>
      </div>

      {state === 'loading' ? (
        <div className="grid gap-4 p-5 sm:grid-cols-3" aria-live="polite">
          {[1, 2, 3].map((item) => <div key={item} className="h-16 animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-800" />)}
        </div>
      ) : state === 'unavailable' ? (
        <div className="p-5 text-sm text-zinc-500 dark:text-zinc-400" role="status">
          {ui(locale, '統計を取得できません。固定値や推測値は表示していません。', 'Statistics are unavailable. No fallback or estimated values are shown.')}
        </div>
      ) : state === 'no-data' || !data ? (
        <div className="p-5 text-sm text-zinc-500 dark:text-zinc-400" role="status">
          {ui(locale, '選択期間に実測イベントはありません。これは0件の確定値とは別の「データなし」です。', 'No measured events exist in this period. This is distinct from a confirmed zero.')}
        </div>
      ) : (
        <>
          <div className="grid gap-px border-b border-zinc-100 bg-zinc-100 sm:grid-cols-3 dark:border-zinc-800 dark:bg-zinc-800">
            <MetricCard label={ui(locale, '閲覧', 'Views')} value={data.totals.views} locale={locale} />
            <MetricCard label={ui(locale, 'ダウンロード', 'Downloads')} value={data.totals.downloads} locale={locale} />
            <MetricCard label={ui(locale, '有効ないいね', 'Active likes')} value={data.totals.likes} locale={locale} />
          </div>

          <div className="p-5">
            {chart ? (
              <div className="min-w-0 overflow-x-auto" data-metric-chart>
                <svg
                  viewBox={`0 0 ${chart.width} ${chart.height}`}
                  className="h-auto min-w-[560px] w-full"
                  role="img"
                  aria-label={ui(locale, '閲覧・ダウンロード・いいねの時系列グラフ', 'Time series of views, downloads, and active likes')}
                >
                  <title>{ui(locale, '実測イベントの時系列', 'Measured event time series')}</title>
                  <desc>{ui(locale, '各点には日付と正確な値のtooltipがあります。', 'Each point has a tooltip with the exact period and value.')}</desc>
                  {[0, 1, 2, 3].map((line) => {
                    const y = 20 + ((chart.height - 40) * line) / 3;
                    return <line key={line} x1="22" x2={chart.width - 22} y1={y} y2={y} stroke="currentColor" strokeOpacity="0.1" />;
                  })}
                  {chartLines.map((line) => (
                    <g key={line.key}>
                      <polyline points={linePoints(data.series, line.key, chart.width, chart.height)} fill="none" stroke={line.color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                      {data.series.map((point, index) => {
                        const max = Math.max(1, ...data.series.map((item) => item[line.key]));
                        const x = 22 + ((chart.width - 44) * index) / Math.max(1, data.series.length - 1);
                        const y = chart.height - 20 - ((chart.height - 40) * point[line.key]) / max;
                        return (
                          <circle key={`${line.key}-${point.bucket_start}`} cx={x} cy={y} r="3.5" fill={line.color}>
                            <title>{`${formatDate(point.bucket_start, locale)} · ${locale === 'ja' ? line.labelJa : line.label}: ${formatNumber(point[line.key], locale)}`}</title>
                          </circle>
                        );
                      })}
                    </g>
                  ))}
                </svg>
                <div className="mt-3 flex flex-wrap gap-4 text-xs text-zinc-500 dark:text-zinc-400" aria-label={ui(locale, 'グラフ凡例', 'Chart legend')}>
                  {chartLines.map((line) => <span key={line.key} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: line.color }} />{locale === 'ja' ? line.labelJa : line.label}</span>)}
                </div>
              </div>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-2 text-xs text-zinc-500 dark:text-zinc-400" data-metric-download-breakdown>
              {(['raw', 'lfs', 'automation'] as const).map((source) => (
                <span key={source} className="rounded-md bg-zinc-100 px-2.5 py-1.5 dark:bg-zinc-800" data-metric-source={source}>
                  {source}: {formatNumber(data.totals.downloads_by_source[source], locale)}
                </span>
              ))}
            </div>

            <details className="mt-4 rounded-lg border border-zinc-200 dark:border-zinc-800">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-zinc-600 dark:text-zinc-300">
                {ui(locale, '日別の正確な値を表示', 'Show exact daily values')}
              </summary>
              <div className="max-h-72 overflow-auto border-t border-zinc-200 dark:border-zinc-800">
                <table className="w-full text-left text-xs" data-metric-table>
                  <thead className="sticky top-0 bg-white text-zinc-400 dark:bg-zinc-900"><tr><th className="px-3 py-2">{ui(locale, '期間', 'Period')}</th><th className="px-3 py-2">{ui(locale, '閲覧', 'Views')}</th><th className="px-3 py-2">{ui(locale, 'DL', 'DL')}</th><th className="px-3 py-2">{ui(locale, 'いいね', 'Likes')}</th></tr></thead>
                  <tbody>{data.series.map((point) => <tr key={point.bucket_start} className="border-t border-zinc-100 dark:border-zinc-800"><td className="whitespace-nowrap px-3 py-2">{formatDate(point.bucket_start, locale)}</td><td className="px-3 py-2">{formatNumber(point.views, locale)}</td><td className="px-3 py-2">{formatNumber(point.downloads, locale)}</td><td className="px-3 py-2">{formatNumber(point.likes, locale)}</td></tr>)}</tbody>
                </table>
              </div>
            </details>
            <p className="mt-3 text-[11px] text-zinc-400" data-metric-updated-at>
              {ui(locale, '最終更新', 'Updated')} {formatDateTime(data.updated_at, locale)} · {ui(locale, '集計時点', 'Generated')} {formatDateTime(data.generated_at, locale)}
            </p>
          </div>
        </>
      )}
    </section>
  );
}

function MetricCard({ label, value, locale }: { label: string; value: number; locale: string }) {
  return (
    <div className="bg-white px-5 py-4 dark:bg-zinc-900">
      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-zinc-400">{label}</p>
      <p className="mt-1 text-xl font-bold tabular-nums text-zinc-900 dark:text-zinc-100">{formatNumber(value, locale)}</p>
    </div>
  );
}
