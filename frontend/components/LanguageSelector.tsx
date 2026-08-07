'use client';

import HfIcon from './HfIcon';
import { useLocale } from './LocaleProvider';

export default function LanguageSelector() {
  const { locale, setLocale, isPending } = useLocale();
  const nextLocale = locale === 'ja' ? 'en' : 'ja';
  const label = locale === 'ja' ? 'English' : '日本語';

  return (
    <button
      type="button"
      onClick={() => setLocale(nextLocale)}
      disabled={isPending}
      className="nyankoface-language-selector"
      aria-label={locale === 'ja' ? 'Switch the interface to English' : 'UIを日本語に切り替える'}
      title={label}
    >
      <HfIcon name="globe" className="h-3.5 w-3.5" />
      <span>{locale === 'ja' ? 'JA' : 'EN'}</span>
    </button>
  );
}

