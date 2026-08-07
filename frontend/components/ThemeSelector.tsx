'use client';

import { useEffect, useState } from 'react';
import { useLocale } from './LocaleProvider';
import { ui } from '@/lib/i18n';

const STORAGE_KEY = 'nyankoface-theme-v2';
const LEGACY_STORAGE_KEY = 'nyankoface-theme';

const themes = [
  { value: 'standard', ja: 'スタンダード', en: 'Standard' },
  { value: 'solarpunk', ja: 'ソーラーパンク', en: 'Solarpunk' },
  { value: 'cyberpunk', ja: 'サイバーパンク', en: 'Cyberpunk' },
] as const;

type ThemeName = (typeof themes)[number]['value'];

function applyTheme(theme: ThemeName) {
  const root = document.documentElement;
  if (theme === 'standard') {
    delete root.dataset.nyankofaceTheme;
  } else {
    root.dataset.nyankofaceTheme = theme;
  }
  localStorage.setItem(STORAGE_KEY, theme);
  document.cookie = `nyankoface-theme=${theme}; Path=/; Max-Age=31536000; SameSite=Lax`;
}

function ThemeIcon({ theme }: { theme: ThemeName }) {
  if (theme === 'solarpunk') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="3.25" />
        <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" />
      </svg>
    );
  }

  if (theme === 'cyberpunk') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m12 3 7 9-7 9-7-9 7-9Z" />
        <path d="m12 8 3 4-3 4-3-4 3-4Z" />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17" />
      <path d="M12 3.5a8.5 8.5 0 0 0 0 17Z" className="nyankoface-theme-icon-fill" />
    </svg>
  );
}

export default function ThemeSelector() {
  const { locale } = useLocale();
  const [theme, setTheme] = useState<ThemeName>('standard');

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeName | null;
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY) as ThemeName | null;
    const initial = themes.some(({ value }) => value === saved)
      ? saved!
      : legacy && legacy !== 'standard' && themes.some(({ value }) => value === legacy)
        ? legacy
        : window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'cyberpunk'
          : 'standard';
    setTheme(initial);
    applyTheme(initial);
  }, []);

  const currentIndex = themes.findIndex(({ value }) => value === theme);
  const nextTheme = themes[(currentIndex + 1) % themes.length];
  const currentLabel = ui(locale, themes[currentIndex].ja, themes[currentIndex].en);
  const nextLabel = ui(locale, nextTheme.ja, nextTheme.en);

  return (
    <button
      type="button"
      className="nyankoface-theme-selector"
      data-theme={theme}
      aria-label={ui(locale, `現在は${currentLabel}テーマ。${nextLabel}へ切り替える`, `Current theme: ${currentLabel}. Switch to ${nextLabel}`)}
      title={ui(locale, `${currentLabel} · ${nextLabel}へ切り替え`, `${currentLabel} · switch to ${nextLabel}`)}
      onClick={() => {
        setTheme(nextTheme.value);
        applyTheme(nextTheme.value);
      }}
    >
      <ThemeIcon theme={theme} />
    </button>
  );
}
