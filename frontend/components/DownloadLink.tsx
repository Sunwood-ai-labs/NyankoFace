'use client';

import type { AnchorHTMLAttributes, MouseEvent } from 'react';

export default function DownloadLink({
  href,
  children,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  function addIdempotencyKey(event: MouseEvent<HTMLAnchorElement>) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    const link = event.currentTarget;
    const downloadId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const url = new URL(link.href, window.location.href);
    url.searchParams.set('download_id', downloadId);
    link.href = url.toString();
  }

  return (
    <a href={href} {...props} onClick={addIdempotencyKey}>
      {children}
    </a>
  );
}
