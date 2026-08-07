export const locales = ['ja', 'en'] as const;

export type Locale = (typeof locales)[number];

export const DEFAULT_LOCALE: Locale = 'ja';
export const LOCALE_COOKIE = 'nyankoface-locale';

export function normalizeLocale(value?: string | null): Locale {
  return value === 'en' ? 'en' : DEFAULT_LOCALE;
}

export function ui<T>(locale: Locale, japanese: T, english: T): T {
  return locale === 'ja' ? japanese : english;
}

