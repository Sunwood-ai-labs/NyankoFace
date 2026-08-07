'use client';

import HfIcon from './HfIcon';
import BrandMark from './BrandMark';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

export default function Footer({ appName }: { appName: string }) {
  const { locale } = useLocale();
  return (
    <footer className="mt-16 border-t border-zinc-200 py-8 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
      <p className="inline-flex items-center gap-2">
        <BrandMark className="h-6 w-6 rounded-md" />
        {ui(locale, `${appName} - ローカルAIコミュニティハブ`, `${appName} - Local AI Community Hub`)}
      </p>
      <p className="mt-1">
        {ui(locale, '基盤：', 'Powered by:')}{' '}
        <a href="/git/" className="inline-flex items-center gap-1 underline hover:text-amber-700 dark:hover:text-amber-400">
          <HfIcon name="code" className="h-3 w-3" />
          Forgejo
        </a>
      </p>
    </footer>
  );
}
