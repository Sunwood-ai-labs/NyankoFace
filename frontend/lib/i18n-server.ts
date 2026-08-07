import { cookies } from 'next/headers';
import { Locale, LOCALE_COOKIE, normalizeLocale } from './i18n';

export async function getLocale(): Promise<Locale> {
  const cookieStore = await cookies();
  return normalizeLocale(cookieStore.get(LOCALE_COOKIE)?.value);
}

