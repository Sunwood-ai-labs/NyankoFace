import type { MetadataRoute } from 'next';
import { getAppName } from '@/lib/app-config';

const BRAND_VERSION = '20260801-cat-v1';

export const dynamic = 'force-dynamic';

export default function manifest(): MetadataRoute.Manifest {
  const appName = getAppName();
  return {
    id: '/',
    name: appName,
    short_name: appName,
    description: 'A local-first AI community hub for models, datasets, Spaces, and knowledge.',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: '#06132e',
    theme_color: '#06132e',
    icons: [
      {
        src: `/brand/pwa-192x192.png?v=${BRAND_VERSION}`,
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: `/brand/nyankoface-cat-logo.png?v=${BRAND_VERSION}`,
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any',
      },
      {
        src: `/brand/maskable-512x512.png?v=${BRAND_VERSION}`,
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
    ],
  };
}
