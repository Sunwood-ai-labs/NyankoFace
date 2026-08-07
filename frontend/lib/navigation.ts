import rawNavigation from '@/public/nyankoface-navigation.json';
import type { HfIconName } from '@/components/HfIcon';

export type NavigationAudience = 'anonymous' | 'authenticated' | 'admin';

export interface NavigationItem {
  id: string;
  href: string;
  icon: HfIconName;
  label: string;
  labelJa: string;
  external?: boolean;
  auth?: 'authenticated' | 'admin';
}

export interface NyankoFaceNavigation {
  version: number;
  brand: { name: string; homeHref: string; markSrc: string };
  primary: NavigationItem[];
  explore: NavigationItem[];
  community: NavigationItem[];
  publish: NavigationItem[];
}

export const nyankoFaceNavigation = rawNavigation as NyankoFaceNavigation;

export function navigationLabel(item: NavigationItem, locale: string): string {
  return locale === 'ja' ? item.labelJa : item.label;
}

export function navigationItemIsCurrent(pathname: string, href: string): boolean {
  if (!href.startsWith('/')) return false;
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function navigationItemsForAudience(
  items: NavigationItem[],
  audience: NavigationAudience,
): NavigationItem[] {
  return items.filter((item) => {
    if (!item.auth) return true;
    if (item.auth === 'admin') return audience === 'admin';
    return audience === 'authenticated' || audience === 'admin';
  });
}
