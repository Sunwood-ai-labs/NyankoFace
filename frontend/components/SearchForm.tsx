'use client';

import { FormEvent, KeyboardEvent } from 'react';
import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';
import { useRouter } from 'next/navigation';
import { startNavigationFeedback } from './NavigationFeedback';
import { classifyNavigationRoute, usesClientNavigation } from '@/lib/navigation-performance';

function targetForSearch(rawQuery: string) {
  const query = rawQuery.trim();
  const strip = (pattern: RegExp) => query.replace(pattern, '').trim();
  if (/^datasets?:/i.test(query)) return { path: '/datasets', query: strip(/^datasets?:\s*/i) };
  if (/^spaces?:/i.test(query)) return { path: '/spaces', query: strip(/^spaces?:\s*/i) };
  if (/^characters?:/i.test(query)) return { path: '/characters', query: strip(/^characters?:\s*/i) };
  if (/^benchmarks?:/i.test(query)) return { path: '/benchmarks', query: strip(/^benchmarks?:\s*/i) };
  if (/^automations?:/i.test(query)) return { path: '/automations', query: strip(/^automations?:\s*/i) };
  if (/^users?:/i.test(query)) return { path: '/git/explore/users', query: strip(/^users?:\s*/i) };
  if (/^repos?:/i.test(query)) return { path: '/git/explore/repos', query: strip(/^repos?:\s*/i) };
  return { path: '/models', query };
}

export default function SearchForm({
  appName,
  className = '',
  compact = false,
}: {
  appName: string;
  className?: string;
  compact?: boolean;
}) {
  const { locale } = useLocale();
  const router = useRouter();
  const navigateToSearch = (rawQuery: string) => {
    const target = targetForSearch(rawQuery);
    const href = target.query ? `${target.path}?q=${encodeURIComponent(target.query)}` : target.path;
    const clientNavigation = usesClientNavigation(classifyNavigationRoute(target.path));
    startNavigationFeedback(href, !clientNavigation);
    if (clientNavigation) router.push(href);
    else window.location.assign(href);
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    navigateToSearch(String(data.get('q') || ''));
  };
  const submitFromKeyboard = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return;
    event.preventDefault();
    navigateToSearch(event.currentTarget.value);
  };

  return (
    <form
      action="/search"
      method="get"
      className={className}
      data-navigation-feedback="off"
      onSubmit={submit}
    >
      <div className="relative">
        <input
          type="search"
          name="q"
          placeholder={ui(locale, 'モデル、データセット、ユーザーを検索…', 'Search models, datasets, users…')}
          aria-label={ui(locale, `${appName}を検索`, `Search ${appName}`)}
          onKeyDown={submitFromKeyboard}
          className={
            compact
              ? 'h-9 w-full rounded-lg border border-zinc-200 bg-white px-3 pl-9 text-sm text-zinc-900 placeholder-zinc-400 focus:border-zinc-300 focus:outline-none focus:ring-2 focus:ring-zinc-200'
              : 'h-9 w-full rounded-lg border border-zinc-200 bg-white px-4 pl-10 text-sm text-zinc-900 shadow-sm placeholder-zinc-400 focus:border-zinc-300 focus:outline-none focus:ring-2 focus:ring-zinc-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100'
          }
        />
        <span className="pointer-events-none absolute left-3 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center text-zinc-400">
          <HfIcon name="search" className="h-3.5 w-3.5" />
        </span>
      </div>
    </form>
  );
}
