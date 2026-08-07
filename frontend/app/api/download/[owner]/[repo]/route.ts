import { getRepo } from '@/lib/forgejo';
import { recordDownloadMetric, type MetricDownloadOutcome, type MetricDownloadSource } from '@/lib/agent-metrics';

export const dynamic = 'force-dynamic';

const FORGEJO_WEB = (process.env.FORGEJO_WEB || 'http://forgejo:3000').replace(/\/$/, '');
const DOWNLOAD_ID_PATTERN = /^[A-Za-z0-9._:-]{1,200}$/;
const OWNER_REPO_PATTERN = /^[A-Za-z0-9._-]{1,100}$/;

function encodePath(value: string): string {
  return value
    .split('/')
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join('/');
}

function isSafeRepositoryPath(value: string): boolean {
  return Boolean(value) && !value.startsWith('/') && !value.includes('\\') && !value.split('/').includes('..');
}

function safeFilename(path: string): string {
  const candidate = path.split('/').pop() || 'download';
  return candidate.replace(/[^A-Za-z0-9._-]+/g, '_').slice(0, 180) || 'download';
}

function outcomeForStatus(status: number): MetricDownloadOutcome {
  return status === 401 || status === 403 ? 'denied' : 'failed';
}

function metricKey(source: MetricDownloadSource, downloadId: string, outcome: MetricDownloadOutcome): string {
  return `${source}:${downloadId.slice(0, 160)}:${outcome}`;
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ owner: string; repo: string }> },
) {
  const { owner, repo } = await params;
  const query = new URL(request.url).searchParams;
  const source = query.get('kind') as MetricDownloadSource | null;
  const refKind = query.get('refKind') || 'branch';
  const branch = query.get('ref') || 'main';
  const path = query.get('path') || '';
  const requestedDownloadId = query.get('download_id') || '';
  const downloadId = DOWNLOAD_ID_PATTERN.test(requestedDownloadId)
    ? requestedDownloadId
    : globalThis.crypto.randomUUID();

  if (
    !OWNER_REPO_PATTERN.test(owner) ||
    !OWNER_REPO_PATTERN.test(repo) ||
    !source ||
    !['raw', 'lfs'].includes(source) ||
    !['branch', 'tag'].includes(refKind) ||
    path.length > 500 ||
    branch.length > 200 ||
    !isSafeRepositoryPath(path) ||
    !isSafeRepositoryPath(branch)
  ) {
    return Response.json({ error: 'Invalid download target.' }, { status: 400 });
  }

  const repository = await getRepo(owner, repo);
  if (!repository) {
    return Response.json({ error: 'The public repository was not found.' }, { status: 404 });
  }

  const upstreamPath = source === 'lfs'
    ? `/${encodePath(owner)}/${encodePath(repo)}/media/${encodeURIComponent(refKind)}/${encodePath(branch)}/${encodePath(path)}`
    : `/${encodePath(owner)}/${encodePath(repo)}/raw/${encodeURIComponent(refKind)}/${encodePath(branch)}/${encodePath(path)}`;
  let upstream: Response;
  try {
    upstream = await fetch(`${FORGEJO_WEB}${upstreamPath}`, {
      cache: 'no-store',
      redirect: 'follow',
      headers: { 'Accept-Encoding': 'identity' },
      signal: request.signal,
    });
  } catch {
    await recordDownloadMetric({
      owner,
      repo,
      source,
      artifactPath: path,
      idempotencyKey: metricKey(source, downloadId, 'failed'),
      outcome: 'failed',
      actorKind: request.headers.get('cookie')?.includes('nyankoface_session=') ? 'authenticated' : 'anonymous',
    });
    return Response.json({ error: 'The file could not be downloaded.' }, { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    const outcome = outcomeForStatus(upstream.status);
    await recordDownloadMetric({
      owner,
      repo,
      source,
      artifactPath: path,
      idempotencyKey: metricKey(source, downloadId, outcome),
      outcome,
      actorKind: request.headers.get('cookie')?.includes('nyankoface_session=') ? 'authenticated' : 'anonymous',
    });
    return Response.json(
      { error: 'The file could not be downloaded.' },
      { status: upstream.status === 401 || upstream.status === 403 || upstream.status === 404 ? 404 : 502 },
    );
  }

  const headers = new Headers();
  headers.set('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
  headers.set('Content-Disposition', `attachment; filename="${safeFilename(path)}"`);
  headers.set('Cache-Control', 'no-store');
  headers.set('X-Content-Type-Options', 'nosniff');
  const length = upstream.headers.get('content-length');
  const contentEncoding = upstream.headers.get('content-encoding');
  if (length && !contentEncoding) headers.set('Content-Length', length);
  const actorKind = request.headers.get('cookie')?.includes('nyankoface_session=') ? 'authenticated' : 'anonymous';
  const reader = upstream.body.getReader();
  let recorded = false;
  const recordOutcome = (outcome: MetricDownloadOutcome) => {
    if (recorded) return;
    recorded = true;
    void recordDownloadMetric({
      owner,
      repo,
      source,
      artifactPath: path,
      idempotencyKey: metricKey(source, downloadId, outcome),
      outcome,
      actorKind,
    });
  };
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const chunk = await reader.read();
        if (chunk.done) {
          recordOutcome('success');
          controller.close();
        } else {
          controller.enqueue(chunk.value);
        }
      } catch {
        recordOutcome('failed');
        controller.error(new Error('The file stream failed.'));
      }
    },
    cancel(reason) {
      recordOutcome('cancelled');
      void reader.cancel(reason);
    },
  });
  return new Response(body, { status: 200, headers });
}
