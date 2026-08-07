'use client';

import { useState } from 'react';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

export default function CloneBlock({ cloneUrl }: { cloneUrl: string }) {
  const { locale } = useLocale();
  const [copied, setCopied] = useState(false);
  const command = `git clone ${cloneUrl}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable — ignore
    }
  }

  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {ui(locale, 'クローン', 'Clone')}
      </p>
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-2.5 shadow-sm">
        <code className="block break-all text-[10px] leading-4 text-zinc-100">
          <span className="mr-1 select-none text-zinc-500">$</span>
          <span className="text-emerald-300">git clone</span>{' '}
          <span className="text-zinc-200">{cloneUrl}</span>
        </code>
        <button
          type="button"
          onClick={copy}
          className="mt-2 inline-flex min-h-8 w-full items-center justify-center rounded-md bg-zinc-700 px-2 py-1.5 text-xs font-medium text-zinc-100 transition-colors hover:bg-zinc-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
        >
          {copied ? ui(locale, 'コピーしました', 'Copied') : ui(locale, 'コマンドをコピー', 'Copy command')}
        </button>
      </div>
    </div>
  );
}
