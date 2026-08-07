'use client';

export default function ExternalSpaceLink({
  href,
  owner,
  repo,
  ariaLabel,
}: {
  href: string;
  owner: string;
  repo: string;
  ariaLabel: string;
}) {
  function recordView() {
    const idempotencyKey = `browser-link:${owner}/${repo}:${performance.timeOrigin}`;
    void fetch(
      `/runner-api/metrics/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/views`,
      {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        keepalive: true,
      },
    ).catch(() => {
      // Navigation must never be blocked when the optional metric write fails.
    });
  }

  return (
    <a
      href={href}
      onClick={recordView}
      className="absolute inset-0 z-0 rounded-xl"
      aria-label={ariaLabel}
    />
  );
}
