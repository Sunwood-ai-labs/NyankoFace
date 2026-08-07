'use client';

import Link from 'next/link';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent,
  type RefObject,
  type SetStateAction,
} from 'react';
import { usePathname, useRouter } from 'next/navigation';
import BrandMark from './BrandMark';
import HfIcon from './HfIcon';
import SearchForm from './SearchForm';
import ThemeSelector from './ThemeSelector';
import LanguageSelector from './LanguageSelector';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';
import { useAuthSession } from './AuthSessionProvider';
import {
  navigationItemIsCurrent,
  navigationItemsForAudience,
  navigationLabel,
  nyankoFaceNavigation,
  type NavigationAudience,
  type NavigationItem,
} from '@/lib/navigation';

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function isSameTabPrimaryClick(event: MouseEvent<HTMLElement>) {
  return event.button === 0
    && !event.defaultPrevented
    && !event.metaKey
    && !event.ctrlKey
    && !event.shiftKey
    && !event.altKey;
}

function useDismissibleDetails(
  detailsRef: RefObject<HTMLDetailsElement | null>,
  triggerRef: RefObject<HTMLElement | null>,
  open: boolean,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (detailsRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [detailsRef, open, setOpen, triggerRef]);
}

function ItemIcon({ item }: { item: NavigationItem }) {
  return (
    <span className="nyankoface-nav-icon">
      <HfIcon name={item.icon} className="h-4 w-4" />
    </span>
  );
}

function MobileItem({ item, pathname, locale, onNavigate }: {
  item: NavigationItem;
  pathname: string;
  locale: string;
  onNavigate: (event: MouseEvent<HTMLElement>) => void;
}) {
  const current = navigationItemIsCurrent(pathname, item.href);
  const content = <><ItemIcon item={item} /><span>{navigationLabel(item, locale)}</span></>;
  const className = "nyankoface-mobile-nav-link";
  if (item.external) {
    return <a href={item.href} className={className} onClick={onNavigate}>{content}</a>;
  }
  return (
    <Link href={item.href} aria-current={current ? 'page' : undefined} className={className} onClick={onNavigate}>
      {content}
    </Link>
  );
}

export default function Navbar({ appName }: { appName: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const { locale } = useLocale();
  const { auth, setAnonymous } = useAuthSession();
  const [loggingOut, setLoggingOut] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [exploreOpen, setExploreOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const mobilePanelRef = useRef<HTMLDivElement>(null);
  const exploreRef = useRef<HTMLDetailsElement>(null);
  const exploreTriggerRef = useRef<HTMLElement>(null);
  const accountRef = useRef<HTMLDetailsElement>(null);
  const accountTriggerRef = useRef<HTMLElement>(null);
  const audience: NavigationAudience = auth.status === 'authenticated'
    ? (auth.isAdmin ? 'admin' : 'authenticated')
    : 'anonymous';
  const publishItems = useMemo(
    () => navigationItemsForAudience(nyankoFaceNavigation.publish, audience),
    [audience],
  );
  const allDirectoryItems = [...nyankoFaceNavigation.primary, ...nyankoFaceNavigation.explore];
  const exploreIsCurrent = nyankoFaceNavigation.explore.some((item) => navigationItemIsCurrent(pathname, item.href));

  useEffect(() => {
    setMobileOpen(false);
    setExploreOpen(false);
    setAccountOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (auth.status !== 'authenticated') setAccountOpen(false);
  }, [auth.status]);

  useDismissibleDetails(exploreRef, exploreTriggerRef, exploreOpen, setExploreOpen);
  useDismissibleDetails(accountRef, accountTriggerRef, accountOpen, setAccountOpen);

  useEffect(() => {
    const desktopQuery = window.matchMedia('(min-width: 1280px)');
    const closeAtDesktop = (query: MediaQueryList | MediaQueryListEvent) => {
      if (query.matches) setMobileOpen(false);
    };
    closeAtDesktop(desktopQuery);
    desktopQuery.addEventListener('change', closeAtDesktop);
    return () => desktopQuery.removeEventListener('change', closeAtDesktop);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const panel = mobilePanelRef.current;
    const focusable = panel ? Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector)) : [];
    focusable[0]?.focus({ preventScroll: true });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMobileOpen(false);
        mobileToggleRef.current?.focus();
        return;
      }
      if (event.key !== 'Tab' || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [mobileOpen]);

  const logout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
      setAnonymous();
      setMobileOpen(false);
      router.refresh();
    } finally {
      setLoggingOut(false);
    }
  };

  const closeMobileOnNavigate = (event: MouseEvent<HTMLElement>) => {
    if (isSameTabPrimaryClick(event)) setMobileOpen(false);
  };

  const closeDetailsOnNavigate = (event: MouseEvent<HTMLElement>) => {
    if (!isSameTabPrimaryClick(event)) return;
    const details = event.currentTarget.closest('details');
    if (!details) return;
    details.open = false;
    if (details === exploreRef.current) setExploreOpen(false);
    if (details === accountRef.current) setAccountOpen(false);
  };

  return (
    <header className="nyankoface-global-header sticky top-0 z-30 border-b border-zinc-200 bg-white/95 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
      <div className="nyankoface-global-navbar mx-auto flex h-16 max-w-[1536px] items-center gap-4 px-4">
        <Link href={nyankoFaceNavigation.brand.homeHref} aria-label={`${nyankoFaceNavigation.brand.name} home`} className="flex shrink-0 items-center gap-2 text-lg font-bold text-zinc-900 dark:text-zinc-100">
          <BrandMark className="h-9 w-9 rounded-lg" />
          <span className="hidden sm:inline">{nyankoFaceNavigation.brand.name}</span>
        </Link>

        <SearchForm appName={appName} className="ml-auto hidden flex-1 sm:ml-6 sm:block sm:max-w-[325px]" />

        <nav aria-label={ui(locale, 'メインナビゲーション', 'Main navigation')} className="ml-auto hidden items-center gap-3 text-sm font-medium xl:flex">
          {nyankoFaceNavigation.primary.map((item) => {
            const current = navigationItemIsCurrent(pathname, item.href);
            return (
              <Link key={item.id} href={item.href} aria-current={current ? 'page' : undefined} className="nyankoface-desktop-nav-link">
                <HfIcon name={item.icon} className="h-3.5 w-3.5" />
                {navigationLabel(item, locale)}
              </Link>
            );
          })}
          <details ref={exploreRef} open={exploreOpen} onToggle={(event) => setExploreOpen(event.currentTarget.open)} className="nyankoface-global-explore group relative">
            <summary ref={exploreTriggerRef} className="nyankoface-explore-trigger" aria-label={ui(locale, 'その他のナビゲーションを開く', 'Open more navigation')}>
              <HfIcon name="bars" className="h-3.5 w-3.5" />
              <span>{ui(locale, 'その他', 'More')}</span>
              {exploreIsCurrent && <span className="sr-only">({ui(locale, '現在のセクション', 'current section')})</span>}
            </summary>
            <div className="nyankoface-explore-menu">
              <section>
                <h2>{ui(locale, '開発ツール', 'Build tools')}</h2>
                <div className="grid grid-cols-2 gap-2">
                  {nyankoFaceNavigation.explore.map((item) => (
                    <Link key={item.id} href={item.href} onClick={closeDetailsOnNavigate} aria-current={navigationItemIsCurrent(pathname, item.href) ? 'page' : undefined} className="nyankoface-explore-card">
                      <ItemIcon item={item} /><span>{navigationLabel(item, locale)}</span>
                    </Link>
                  ))}
                </div>
              </section>
              <div className="grid content-start gap-5">
                <section>
                  <h2>{ui(locale, 'コミュニティ', 'Community')}</h2>
                  {nyankoFaceNavigation.community.map((item) => (
                    <a key={item.id} href={item.href} onClick={closeDetailsOnNavigate} aria-current={navigationItemIsCurrent(pathname, item.href) ? 'page' : undefined} className="nyankoface-explore-row">
                      {navigationLabel(item, locale)}
                    </a>
                  ))}
                </section>
                {publishItems.length > 0 && <section>
                  <h2>{ui(locale, '作成・公開', 'Create & publish')}</h2>
                  {publishItems.map((item) => <a key={item.id} href={item.href} onClick={closeDetailsOnNavigate} className="nyankoface-explore-row">{navigationLabel(item, locale)}</a>)}
                </section>}
              </div>
            </div>
          </details>
        </nav>

        <div className="hidden xl:block"><ThemeSelector /></div>
        <div className="hidden xl:block"><LanguageSelector /></div>

        {auth.status === 'loading' ? (
          <div className="hidden h-9 w-24 animate-pulse rounded-full bg-zinc-100 xl:block dark:bg-zinc-800" aria-label={ui(locale, 'アカウント情報を読み込み中', 'Loading account')} />
        ) : auth.status === 'authenticated' ? (
          <details ref={accountRef} open={accountOpen} onToggle={(event) => setAccountOpen(event.currentTarget.open)} className="group relative hidden xl:block" data-auth-state="authenticated">
            <summary ref={accountTriggerRef} className="nyankoface-account-trigger" aria-label={ui(locale, 'アカウントメニューを開く', 'Open account menu')}>
              {auth.avatarUrl ? <img src={auth.avatarUrl} alt="" className="h-7 w-7 rounded-full object-cover" /> : <span className="nyankoface-account-fallback">{auth.username.charAt(0)}</span>}
              <span className="max-w-28 truncate">{auth.displayName || auth.username}</span>
            </summary>
            <div className="nyankoface-account-menu">
              <p>{ui(locale, 'ログイン中', 'Signed in as')} <strong>{auth.username}</strong></p>
              <a href={`/git/${auth.username}`} onClick={closeDetailsOnNavigate}><HfIcon name="user" className="h-4 w-4" />{ui(locale, 'プロフィール', 'Profile')}</a>
              <a href="/git/user/settings" onClick={closeDetailsOnNavigate}><HfIcon name="gear" className="h-4 w-4" />{ui(locale, '設定', 'Settings')}</a>
              {auth.isAdmin && <a href="/git/admin" onClick={closeDetailsOnNavigate}><HfIcon name="gear" className="h-4 w-4" />{ui(locale, '管理', 'Administration')}</a>}
              <button type="button" onClick={(event) => { closeDetailsOnNavigate(event); void logout(); }} disabled={loggingOut}><HfIcon name="logout" className="h-4 w-4" />{loggingOut ? ui(locale, 'ログアウト中…', 'Logging out…') : ui(locale, 'ログアウト', 'Log out')}</button>
            </div>
          </details>
        ) : (
          <div className="hidden shrink-0 items-center gap-3 text-sm font-semibold xl:flex" data-auth-state="anonymous">
            <a href="/git/user/login" className="nyankoface-login-action">{ui(locale, 'ログイン', 'Log in')}</a>
            <a href="/git/user/sign_up" className="nyankoface-signup-action">{ui(locale, '新規登録', 'Sign up')}</a>
          </div>
        )}

        <button ref={mobileToggleRef} type="button" className="nyankoface-mobile-menu-toggle ml-auto xl:hidden" aria-expanded={mobileOpen} aria-controls="nyankoface-mobile-navigation" aria-label={mobileOpen ? ui(locale, 'メニューを閉じる', 'Close menu') : ui(locale, 'メニューを開く', 'Open menu')} onClick={() => setMobileOpen((open) => !open)}>
          <HfIcon name={mobileOpen ? 'plus' : 'bars'} className={`h-4 w-4 ${mobileOpen ? 'rotate-45' : ''}`} />
        </button>
      </div>

      {mobileOpen && <div className="nyankoface-mobile-layer xl:hidden">
        <button type="button" className="nyankoface-mobile-backdrop" aria-label={ui(locale, 'メニューを閉じる', 'Close menu')} onClick={() => setMobileOpen(false)} />
        <div ref={mobilePanelRef} id="nyankoface-mobile-navigation" role="dialog" aria-modal="true" aria-label={ui(locale, 'サイトナビゲーション', 'Site navigation')} className="nyankoface-mobile-panel">
          <SearchForm appName={appName} className="mb-3" compact />
          <div className="mb-3 flex items-center gap-2 border-b border-zinc-200 pb-3 dark:border-zinc-800"><ThemeSelector /><LanguageSelector /></div>
          {auth.status === 'authenticated' ? <section className="nyankoface-mobile-section">
            <h2>{ui(locale, 'アカウント', 'Account')}</h2>
            <a href={`/git/${auth.username}`} className="nyankoface-mobile-nav-link" onClick={closeMobileOnNavigate}><ItemIcon item={{ id: 'profile', href: '', icon: 'user', label: '', labelJa: '' }} /><span className="truncate font-bold">{auth.displayName || auth.username}</span></a>
            <a href="/git/user/settings" className="nyankoface-mobile-nav-link" onClick={closeMobileOnNavigate}><ItemIcon item={{ id: 'settings', href: '', icon: 'gear', label: '', labelJa: '' }} />{ui(locale, '設定', 'Settings')}</a>
            {auth.isAdmin && <a href="/git/admin" className="nyankoface-mobile-nav-link" onClick={closeMobileOnNavigate}><ItemIcon item={{ id: 'admin', href: '', icon: 'gear', label: '', labelJa: '' }} />{ui(locale, '管理', 'Administration')}</a>}
            <button type="button" onClick={logout} disabled={loggingOut} className="nyankoface-mobile-nav-link text-left text-rose-700 disabled:opacity-50"><ItemIcon item={{ id: 'logout', href: '', icon: 'logout', label: '', labelJa: '' }} />{ui(locale, 'ログアウト', 'Log out')}</button>
          </section> : auth.status === 'anonymous' ? <section className="nyankoface-mobile-section border-b border-zinc-200 pb-3 dark:border-zinc-800">
            <h2>{ui(locale, 'アカウント', 'Account')}</h2>
            <div className="flex gap-2">
              <a href="/git/user/login" className="nyankoface-login-action" onClick={closeMobileOnNavigate}>{ui(locale, 'ログイン', 'Log in')}</a>
              <a href="/git/user/sign_up" className="nyankoface-signup-action" onClick={closeMobileOnNavigate}>{ui(locale, '新規登録', 'Sign up')}</a>
            </div>
          </section> : null}
          <nav aria-label={ui(locale, 'モバイルナビゲーション', 'Mobile navigation')}>
            <section className="nyankoface-mobile-section"><h2>{ui(locale, '探す', 'Explore')}</h2>{allDirectoryItems.map((item) => <MobileItem key={item.id} item={item} pathname={pathname} locale={locale} onNavigate={closeMobileOnNavigate} />)}</section>
            <section className="nyankoface-mobile-section"><h2>{ui(locale, 'コミュニティ', 'Community')}</h2>{nyankoFaceNavigation.community.map((item) => <MobileItem key={item.id} item={item} pathname={pathname} locale={locale} onNavigate={closeMobileOnNavigate} />)}</section>
            {publishItems.length > 0 && <section className="nyankoface-mobile-section"><h2>{ui(locale, '作成・公開', 'Create & publish')}</h2>{publishItems.map((item) => <MobileItem key={item.id} item={item} pathname={pathname} locale={locale} onNavigate={closeMobileOnNavigate} />)}</section>}
          </nav>
        </div>
      </div>}
    </header>
  );
}
