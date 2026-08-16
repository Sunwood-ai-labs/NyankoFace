'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { PagesInspection } from '@/lib/forgejo';
import { ui } from '@/lib/i18n';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { shareablePublicUrl } from '@/lib/public-origin';

const PAGES_GUIDE = 'https://sunwood-ai-labs.github.io/NyankoFace/guide/pages';

export default function PagesStatusCard({ inspection, publicOrigin }: { inspection: PagesInspection; publicOrigin?: string }) {
  const { locale } = useLocale();
  const [copied, setCopied] = useState(false);
  const published = inspection.status === 'published' && Boolean(inspection.public_url);
  const unavailable = inspection.status === 'error';

  async function copyPublicUrl() {
    if (!inspection.public_url) return;
    try {
      await navigator.clipboard.writeText(shareablePublicUrl(inspection.public_url, publicOrigin) || inspection.public_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section
      className={`rounded-lg border p-4 ${
        published
          ? 'border-indigo-200 bg-gradient-to-br from-indigo-50 to-white dark:border-indigo-900 dark:from-indigo-950/30 dark:to-zinc-900'
          : 'border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900'
      }`}
      data-pages-status={inspection.status}
    >
      <div className="flex items-center justify-between gap-3">
        <p className={`text-xs font-semibold uppercase tracking-wide ${
          published ? 'text-indigo-700 dark:text-indigo-300' : 'text-zinc-600 dark:text-zinc-300'
        }`}>
          NyankoFace Pages
        </p>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
          published
            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
            : unavailable
              ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300'
        }`}>
          {published
            ? ui(locale, '公開中', 'Published')
            : unavailable
              ? ui(locale, '確認できません', 'Unavailable')
              : ui(locale, '未設定', 'Not configured')}
        </span>
      </div>

      {published ? (
        <>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
            {ui(locale, '公開元: ', 'Published from: ')}
            <code className="rounded bg-white/70 px-1.5 py-0.5 text-xs dark:bg-zinc-950/70">
              {inspection.source === 'gh-pages'
                ? 'gh-pages/index.html'
                : `${inspection.default_branch}/docs/index.html`}
            </code>
          </p>
          <a
            href={inspection.public_url || '#'}
            target="_blank"
            rel="noreferrer"
            className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg bg-indigo-700 px-3 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-indigo-800 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
          >
            <HfIcon name="globe" className="h-3.5 w-3.5" />
            {ui(locale, 'サイトを見る', 'Visit site')}
          </a>
          <button
            type="button"
            onClick={copyPublicUrl}
            className="nyankoface-pages-secondary mt-2 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-lg border border-indigo-200 bg-white px-3 text-sm font-medium text-indigo-800 transition hover:bg-indigo-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:border-indigo-800 dark:bg-zinc-950 dark:text-indigo-200 dark:hover:bg-indigo-950/40"
          >
            <HfIcon name="link" className="h-3.5 w-3.5" />
            {copied ? ui(locale, 'URLをコピーしました', 'URL copied') : ui(locale, '公開URLをコピー', 'Copy public URL')}
          </button>
          <Link
            href={`/pages/deploy?owner=${encodeURIComponent(inspection.owner)}&repo=${encodeURIComponent(inspection.repo)}`}
            className="mt-2 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900"
          >
            <HfIcon name="gear" className="h-3.5 w-3.5" />
            {ui(locale, 'Pagesを管理', 'Manage Pages')}
          </Link>
        </>
      ) : (
        <>
          <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
            {unavailable
              ? ui(locale, 'Pagesの公開状態を確認できませんでした。少し待ってから再読み込みしてください。', 'Pages status could not be checked. Reload after a short wait.')
              : ui(locale, '公開に必要な index.html が見つかりません。次のどちらかを追加してください。', 'No publishable index.html was found. Add either of the following:')}
          </p>
          {!unavailable ? (
            <ul className="mt-3 space-y-2 text-xs text-zinc-600 dark:text-zinc-300">
              {inspection.checks.map((check) => (
                <li key={check.id} className="flex items-start gap-2">
                  <span className="mt-0.5 font-semibold text-rose-600 dark:text-rose-400" aria-hidden="true">×</span>
                  <code className="break-all rounded bg-zinc-100 px-1.5 py-0.5 dark:bg-zinc-800">
                    {check.source === 'gh-pages' ? 'gh-pages/index.html' : `${inspection.default_branch}/docs/index.html`}
                  </code>
                </li>
              ))}
            </ul>
          ) : null}
          {!unavailable ? (
            <Link
              href={`/pages/deploy?owner=${encodeURIComponent(inspection.owner)}&repo=${encodeURIComponent(inspection.repo)}`}
              className="nyankoface-pages-primary mt-3 inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-lg bg-zinc-950 px-3 text-sm font-semibold text-white transition hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white"
            >
              <HfIcon name="pages" className="h-3.5 w-3.5" />
              {ui(locale, 'Pagesとして公開する', 'Publish with Pages')}
            </Link>
          ) : null}
        </>
      )}

      <a
        href={locale === 'ja' ? 'https://sunwood-ai-labs.github.io/NyankoFace/ja/guide/pages' : PAGES_GUIDE}
        target="_blank"
        rel="noreferrer"
        className="nyankoface-pages-guide mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700 hover:underline dark:text-indigo-300"
      >
        {ui(locale, 'Pagesの設定ガイド', 'Pages setup guide')}
        <HfIcon name="external" className="h-3 w-3" />
      </a>
    </section>
  );
}
