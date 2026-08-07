'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  classifyNavigationRoute,
  NavigationCacheState,
  NavigationOutcome,
  NavigationSample,
  navigationPathSearch,
  isSameNavigationDestination,
  hasCommittedNavigationDestination,
  pageHideOutcome,
  shouldStartHistoryNavigation,
  usesClientNavigation,
} from '@/lib/navigation-performance';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

type ActiveNavigation = {
  target: string;
  startedAt: number;
  feedbackAt: number;
  anchor: HTMLAnchorElement | null;
  cache: NavigationCacheState;
  sourceHeading: HTMLElement | null;
  sourcePathname: string;
  documentNavigation: boolean;
  timedOut?: boolean;
};

const BAR_DELAY_MS = 70;
const NAVIGATION_TIMEOUT_MS = 15_000;
const NAVIGATION_START_EVENT = 'nyankoface:navigation-start';

type NavigationStartDetail = {
  target: string;
  documentNavigation: boolean;
};

export function startNavigationFeedback(target: string, documentNavigation = false) {
  window.dispatchEvent(new CustomEvent<NavigationStartDetail>(NAVIGATION_START_EVENT, {
    detail: { target, documentNavigation },
  }));
}

function recordSample(sample: NavigationSample) {
  const body = JSON.stringify(sample);
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/api/performance/navigation', new Blob([body], { type: 'application/json' }));
    return;
  }
  void fetch('/api/performance/navigation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    keepalive: true,
  });
}

export default function NavigationFeedback() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { locale } = useLocale();
  const activeRef = useRef<ActiveNavigation | null>(null);
  const locationRef = useRef<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const barDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [phase, setPhase] = useState<'idle' | 'pending' | 'timeout'>('idle');
  const [showBar, setShowBar] = useState(false);
  const [retryTarget, setRetryTarget] = useState<string | null>(null);

  const clearTimers = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (barDelayRef.current) clearTimeout(barDelayRef.current);
    timeoutRef.current = null;
    barDelayRef.current = null;
  }, []);

  const finish = useCallback((outcome: NavigationOutcome) => {
    const active = activeRef.current;
    if (!active) return;
    clearTimers();
    active.anchor?.removeAttribute('data-nyankoface-navigation-pending');
    active.anchor?.removeAttribute('aria-busy');
    const now = performance.now();
    if (!active.timedOut) {
      recordSample({
        route: classifyNavigationRoute(new URL(active.target, window.location.href).pathname),
        durationMs: Math.max(0, Math.round(now - active.startedAt)),
        feedbackMs: Math.max(0, Math.round((active.feedbackAt || now) - active.startedAt)),
        outcome,
        viewport: window.matchMedia('(max-width: 639px)').matches ? 'mobile' : 'desktop',
        cache: active.cache,
      });
    }
    activeRef.current = null;
    setShowBar(false);
    setPhase('idle');
    setRetryTarget(null);
  }, [clearTimers]);

  const begin = useCallback((
    target: string,
    anchor: HTMLAnchorElement | null,
    documentNavigation = false,
    sourceLocation?: { pathname: string },
  ) => {
    const current = activeRef.current;
    if (
      current
      && isSameNavigationDestination(
        new URL(current.target, window.location.href),
        new URL(target, window.location.href),
      )
      && !current.timedOut
    ) return false;
    if (current) finish('cancelled');
    let cache: NavigationCacheState = 'cold';
    try {
      const key = `nyankoface-navigation-visit:${classifyNavigationRoute(new URL(target, window.location.href).pathname)}`;
      cache = sessionStorage.getItem(key) ? 'warm' : 'cold';
      sessionStorage.setItem(key, '1');
    } catch {
      cache = 'cold';
    }
    const active: ActiveNavigation = {
      target,
      startedAt: performance.now(),
      feedbackAt: 0,
      anchor,
      cache,
      sourceHeading: document.querySelector<HTMLElement>('main h1'),
      sourcePathname: sourceLocation?.pathname ?? window.location.pathname,
      documentNavigation,
    };
    activeRef.current = active;
    anchor?.setAttribute('data-nyankoface-navigation-pending', 'true');
    anchor?.setAttribute('aria-busy', 'true');
    setRetryTarget(null);
    setPhase('pending');
    requestAnimationFrame(() => {
      if (activeRef.current === active) active.feedbackAt = performance.now();
    });
    barDelayRef.current = setTimeout(() => setShowBar(true), BAR_DELAY_MS);
    timeoutRef.current = setTimeout(() => {
      if (activeRef.current !== active) return;
      active.anchor?.removeAttribute('data-nyankoface-navigation-pending');
      active.anchor?.removeAttribute('aria-busy');
      recordSample({
        route: classifyNavigationRoute(new URL(active.target, window.location.href).pathname),
        durationMs: NAVIGATION_TIMEOUT_MS,
        feedbackMs: Math.max(0, Math.round((active.feedbackAt || performance.now()) - active.startedAt)),
        outcome: 'timeout',
        viewport: window.matchMedia('(max-width: 639px)').matches ? 'mobile' : 'desktop',
        cache: active.cache,
      });
      active.timedOut = true;
      clearTimers();
      setShowBar(false);
      setRetryTarget(active.target);
      setPhase('timeout');
    }, NAVIGATION_TIMEOUT_MS);
    return true;
  }, [clearTimers, finish]);

  useEffect(() => {
    const handleClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
        || !(event.target instanceof Element)
      ) return;
      const anchor = event.target.closest('a');
      if (
        !anchor
        || anchor.hasAttribute('download')
        || (anchor.target && anchor.target !== '_self')
        || anchor.dataset.navigationFeedback === 'off'
      ) return;
      const target = new URL(anchor.href, window.location.href);
      if (target.origin !== window.location.origin) return;
      const current = new URL(window.location.href);
      if (isSameNavigationDestination(target, current)) return;
      const route = classifyNavigationRoute(target.pathname);
      const clientNavigation = usesClientNavigation(route);
      if (!begin(target.href, anchor, !clientNavigation)) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (!clientNavigation) return;
      event.preventDefault();
      router.push(target.href);
    };
    const handlePopState = () => {
      const previousPathSearch = locationRef.current;
      const currentPathSearch = navigationPathSearch(window.location);
      locationRef.current = currentPathSearch;
      if (
        previousPathSearch !== null
        && !shouldStartHistoryNavigation(previousPathSearch, window.location)
      ) {
        const active = activeRef.current;
        if (active) {
          const activeTarget = new URL(active.target, window.location.href);
          if (`${activeTarget.pathname}${activeTarget.search}` !== currentPathSearch) {
            finish('cancelled');
          }
        }
        return;
      }
      if (previousPathSearch === null) {
        begin(window.location.href, null);
        return;
      }
      const sourceUrl = new URL(previousPathSearch, window.location.origin);
      begin(window.location.href, null, false, {
        pathname: sourceUrl.pathname,
      });
    };
    const handleSubmit = (event: SubmitEvent) => {
      if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
      const form = event.target;
      if (
        form.method.toLowerCase() !== 'get'
        || (form.target && form.target !== '_self')
        || form.dataset.navigationFeedback === 'off'
      ) return;
      const target = new URL(form.action || window.location.href, window.location.href);
      if (target.origin !== window.location.origin) return;
      const query = new URLSearchParams();
      const formData = new FormData(form);
      const submitter = event.submitter;
      if (
        (submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement)
        && submitter.name
      ) formData.append(submitter.name, submitter.value);
      for (const [key, value] of formData) {
        if (typeof value === 'string') query.append(key, value);
      }
      target.search = query.toString();
      const current = new URL(window.location.href);
      if (isSameNavigationDestination(target, current)) return;
      const clientNavigation = usesClientNavigation(classifyNavigationRoute(target.pathname));
      if (!begin(target.href, null, !clientNavigation)) {
        event.preventDefault();
        return;
      }
      if (!clientNavigation) return;
      event.preventDefault();
      router.push(target.href);
    };
    const handlePageHide = () => {
      const active = activeRef.current;
      if (!active) return;
      finish(pageHideOutcome(active.documentNavigation));
    };
    const handleProgrammaticNavigation = (event: Event) => {
      const detail = (event as CustomEvent<NavigationStartDetail>).detail;
      if (!detail?.target) return;
      const resolvedTarget = new URL(detail.target, window.location.href);
      const current = new URL(window.location.href);
      if (isSameNavigationDestination(resolvedTarget, current)) return;
      begin(resolvedTarget.href, null, detail.documentNavigation);
    };
    document.addEventListener('click', handleClick, true);
    document.addEventListener('submit', handleSubmit, true);
    window.addEventListener('popstate', handlePopState);
    window.addEventListener('pagehide', handlePageHide);
    window.addEventListener(NAVIGATION_START_EVENT, handleProgrammaticNavigation);
    return () => {
      document.removeEventListener('click', handleClick, true);
      document.removeEventListener('submit', handleSubmit, true);
      window.removeEventListener('popstate', handlePopState);
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener(NAVIGATION_START_EVENT, handleProgrammaticNavigation);
      clearTimers();
    };
  }, [begin, clearTimers, finish, router]);

  useEffect(() => {
    locationRef.current = navigationPathSearch(window.location);
    const completedNavigation = activeRef.current;
    if (!completedNavigation) return;
    let stopped = false;
    let focusAllowed = true;
    let observer: MutationObserver | null = null;
    let firstFrame = 0;
    let secondFrame = 0;
    const stopWaiting = () => {
      stopped = true;
      observer?.disconnect();
      observer = null;
      cancelAnimationFrame(firstFrame);
      cancelAnimationFrame(secondFrame);
      document.removeEventListener('pointerdown', cancelFocus, true);
      document.removeEventListener('keydown', cancelFocus, true);
    };
    const cancelFocus = () => {
      focusAllowed = false;
      document.removeEventListener('pointerdown', cancelFocus, true);
      document.removeEventListener('keydown', cancelFocus, true);
    };
    const finishWhenReady = () => {
      if (
        stopped
        || document.querySelector('.nyankoface-route-skeleton, [aria-label="Loading repository statistics"]')
      ) return false;
      const heading = document.querySelector<HTMLElement>('main h1');
      const target = new URL(completedNavigation.target, window.location.href);
      const targetPathSearch = navigationPathSearch(target);
      const currentPathSearch = navigationPathSearch({ pathname, search: searchParams.toString() });
      if (!hasCommittedNavigationDestination({
        targetPathSearch,
        currentPathSearch,
      })) return false;
      if (
        completedNavigation.sourcePathname !== pathname
        && (!heading || heading === completedNavigation.sourceHeading)
      ) return false;
      const outcome: NavigationOutcome = document.querySelector('[data-nyankoface-route-error="true"]')
        ? 'error'
        : 'success';
      finish(outcome);
      if (focusAllowed && heading) {
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
      }
      stopWaiting();
      return true;
    };
    document.addEventListener('pointerdown', cancelFocus, true);
    document.addEventListener('keydown', cancelFocus, true);
    firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        if (finishWhenReady()) return;
        observer = new MutationObserver(() => finishWhenReady());
        observer.observe(document.querySelector('main') ?? document.body, { childList: true, subtree: true });
      });
    });
    return stopWaiting;
  }, [finish, pathname, searchParams]);

  const retry = () => {
    if (!retryTarget) return;
    const target = retryTarget;
    const route = classifyNavigationRoute(new URL(target, window.location.href).pathname);
    const clientNavigation = usesClientNavigation(route);
    activeRef.current = null;
    if (!begin(target, null, !clientNavigation)) return;
    if (clientNavigation) router.push(target);
    else window.location.assign(target);
  };

  const dismiss = () => {
    const active = activeRef.current;
    active?.anchor?.removeAttribute('data-nyankoface-navigation-pending');
    active?.anchor?.removeAttribute('aria-busy');
    activeRef.current = null;
    clearTimers();
    setShowBar(false);
    setRetryTarget(null);
    setPhase('idle');
  };

  return (
    <>
      <div
        className={`nyankoface-navigation-progress ${showBar && phase === 'pending' ? 'nyankoface-navigation-progress--visible' : ''}`}
        role="progressbar"
        aria-label={ui(locale, 'ページを読み込み中', 'Loading page')}
        aria-hidden={phase !== 'pending'}
      >
        <span />
      </div>
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {phase === 'pending'
          ? ui(locale, 'ページを読み込んでいます。', 'Loading the next page.')
          : phase === 'timeout'
            ? ui(locale, '読み込みがタイムアウトしました。', 'Loading timed out.')
            : ''}
      </p>
      {phase === 'timeout' ? (
        <aside className="nyankoface-navigation-timeout" role="alert">
          <div>
            <strong>{ui(locale, '読み込みに時間がかかっています', 'This page is taking too long')}</strong>
            <p>{ui(locale, '接続を確認して、もう一度お試しください。', 'Check the connection and try again.')}</p>
          </div>
          <button type="button" onClick={retry}>{ui(locale, '再試行', 'Retry')}</button>
          <button type="button" onClick={dismiss} aria-label={ui(locale, '閉じる', 'Dismiss')}>×</button>
        </aside>
      ) : null}
    </>
  );
}
