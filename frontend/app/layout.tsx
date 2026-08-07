import type { Metadata } from 'next';
import './globals.css';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import LocaleProvider from '@/components/LocaleProvider';
import { getLocale } from '@/lib/i18n-server';
import { ui } from '@/lib/i18n';
import { getAppName } from '@/lib/app-config';
import { headers } from 'next/headers';
import AuthSessionProvider from '@/components/AuthSessionProvider';
import { forgejoBrowserSession } from '@/lib/forgejo-session';
import NavigationFeedback from '@/components/NavigationFeedback';
import { Suspense } from 'react';

const BRAND_VERSION = '20260801-cat-v1';

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  const appName = getAppName();
  const publicBaseUrl = process.env.PUBLIC_BASE_URL?.trim();
  return {
    ...(publicBaseUrl ? { metadataBase: new URL(publicBaseUrl) } : {}),
    title: ui(locale, `${appName} - ローカルAIコミュニティハブ`, `${appName} - Local AI Community Hub`),
    description: ui(
      locale,
      'Forgejoを基盤に、モデル、データセット、Space、ナレッジを共有できるローカルAIプラットフォーム。',
      'A local AI platform for sharing models, datasets, Spaces, and knowledge, backed by Forgejo.',
    ),
    manifest: `/manifest.webmanifest?v=${BRAND_VERSION}`,
    icons: {
      icon: [
        { url: `/brand/favicon.svg?v=${BRAND_VERSION}`, type: 'image/svg+xml', sizes: 'any' },
        { url: `/brand/favicon-16x16.png?v=${BRAND_VERSION}`, type: 'image/png', sizes: '16x16' },
        { url: `/brand/favicon-32x32.png?v=${BRAND_VERSION}`, type: 'image/png', sizes: '32x32' },
        { url: `/brand/favicon-48x48.png?v=${BRAND_VERSION}`, type: 'image/png', sizes: '48x48' },
      ],
      shortcut: `/favicon.ico?v=${BRAND_VERSION}`,
      apple: [{ url: `/apple-icon.png?v=${BRAND_VERSION}`, type: 'image/png', sizes: '180x180' }],
      other: [{ rel: 'mask-icon', url: `/brand/mask-icon.svg?v=${BRAND_VERSION}`, color: '#14dee1' }],
    },
    openGraph: {
      images: [{ url: `/brand/nyankoface-cat-logo.png?v=${BRAND_VERSION}`, width: 512, height: 512, alt: `${appName} cat mark` }],
    },
    twitter: {
      card: 'summary',
      images: [`/brand/nyankoface-cat-logo.png?v=${BRAND_VERSION}`],
    },
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const appName = getAppName();
  const requestHeaders = await headers();
  const initialSession = await forgejoBrowserSession(requestHeaders.get('cookie') || '');
  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        <meta id="nyankoface-theme-color" name="theme-color" content="#ffffff" />
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => { try { const valid = ['standard', 'solarpunk', 'cyberpunk']; const saved = localStorage.getItem('nyankoface-theme-v2'); const legacy = localStorage.getItem('nyankoface-theme'); const theme = valid.includes(saved) ? saved : (legacy && legacy !== 'standard' && valid.includes(legacy) ? legacy : (matchMedia('(prefers-color-scheme: dark)').matches ? 'cyberpunk' : 'standard')); if (theme === 'standard') delete document.documentElement.dataset.nyankofaceTheme; else document.documentElement.dataset.nyankofaceTheme = theme; const syncThemeColor = () => { const selected = document.documentElement.dataset.nyankofaceTheme || 'standard'; const colors = { standard: '#ffffff', solarpunk: '#f5f8ef', cyberpunk: '#06132e' }; document.querySelector('#nyankoface-theme-color')?.setAttribute('content', colors[selected] || colors.standard); }; syncThemeColor(); new MutationObserver(syncThemeColor).observe(document.documentElement, { attributes: true, attributeFilter: ['data-nyankoface-theme'] }); document.cookie = 'nyankoface-theme=' + theme + '; Path=/; Max-Age=31536000; SameSite=Lax'; } catch {} })();`,
          }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => { document.addEventListener('click', (event) => { if (event.defaultPrevented || event.button !== 0 || !(event.target instanceof Element)) return; const summary = event.target.closest('summary'); const details = summary?.parentElement; if (!summary || details?.tagName !== 'DETAILS') return; const wasOpen = details.hasAttribute('open'); requestAnimationFrame(() => { if (details.hasAttribute('open') === wasOpen) details.open = !wasOpen; }); }, { passive: true }); })();`,
          }}
        />
      </head>
      <body className="min-h-screen bg-white text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <LocaleProvider initialLocale={locale}>
          <AuthSessionProvider initialSession={initialSession}>
            <Suspense fallback={null}>
              <NavigationFeedback />
            </Suspense>
            <Navbar appName={appName} />
            <main
              data-nyankoface-page-frame
              className="nyankoface-page-frame mx-auto w-full max-w-[1600px] py-0"
            >
              {children}
            </main>
            <Footer appName={appName} />
          </AuthSessionProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
