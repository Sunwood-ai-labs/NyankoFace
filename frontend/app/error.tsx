'use client';

import BrandMark from '@/components/BrandMark';
import { useLocale } from '@/components/LocaleProvider';
import { ui } from '@/lib/i18n';
import Link from 'next/link';

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { locale } = useLocale();

  return (
    <section
      className="mx-auto grid min-h-[60vh] max-w-xl place-items-center px-4 py-16 text-center"
      data-nyankoface-route-error="true"
    >
      <div>
        <BrandMark className="mx-auto h-16 w-16 rounded-2xl" />
        <h1 className="mt-6 text-3xl font-bold">{ui(locale, 'ページを読み込めませんでした', 'Could not load this page')}</h1>
        <p className="mt-3 text-zinc-600 dark:text-zinc-300">{ui(locale, 'もう一度試すか、プラットフォームのホームへ戻ってください。', 'Try the request again or return to the platform home.')}</p>
        <div className="mt-6 flex justify-center gap-3">
          <button type="button" onClick={reset} className="rounded-lg bg-zinc-950 px-4 py-2 font-semibold text-white dark:bg-white dark:text-zinc-950">
            {ui(locale, 'もう一度試す', 'Try again')}
          </button>
          <Link href="/" className="rounded-lg border border-zinc-300 px-4 py-2 font-semibold dark:border-zinc-700">{ui(locale, 'ホームを開く', 'Open home')}</Link>
        </div>
      </div>
    </section>
  );
}
