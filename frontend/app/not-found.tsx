import Link from 'next/link';
import BrandMark from '@/components/BrandMark';
import { ui } from '@/lib/i18n';
import { getLocale } from '@/lib/i18n-server';

export default async function NotFoundPage() {
  const locale = await getLocale();

  return (
    <section className="mx-auto grid min-h-[60vh] max-w-xl place-items-center px-4 py-16 text-center">
      <div>
        <BrandMark className="mx-auto h-16 w-16 rounded-2xl" />
        <p className="mt-6 text-sm font-bold uppercase tracking-[0.18em] text-teal-700 dark:text-teal-300">404</p>
        <h1 className="mt-2 text-3xl font-bold">{ui(locale, 'ページが見つかりません', 'Page not found')}</h1>
        <p className="mt-3 text-zinc-600 dark:text-zinc-300">{ui(locale, 'ページが移動したか、非公開になったか、存在しない可能性があります。', 'The page may have moved, become private, or no longer exist.')}</p>
        <Link href="/" className="mt-6 inline-flex rounded-lg bg-zinc-950 px-4 py-2 font-semibold text-white dark:bg-white dark:text-zinc-950">
          {ui(locale, 'ホームを開く', 'Open home')}
        </Link>
      </div>
    </section>
  );
}
