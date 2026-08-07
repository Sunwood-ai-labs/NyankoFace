import 'server-only';

import { NextRequest, NextResponse } from 'next/server';
import { forgejoBrowserSession } from './forgejo-session';
import { controlToken, RUNNER_API } from './space-control';

const FORGEJO_API = process.env.FORGEJO_API || 'http://forgejo:3000/api/v1';
const FORGEJO_WEB = process.env.FORGEJO_WEB || 'http://forgejo:3000';

export interface PagesAuthorization {
  denied: Response | null;
  actor: string;
}

export async function canDeployPages(
  request: NextRequest,
  owner: string,
  repo: string,
): Promise<PagesAuthorization> {
  const cookie = request.headers.get('cookie') || '';
  const session = await forgejoBrowserSession(cookie);
  if (!session.authenticated || !session.username) {
    return {
      denied: NextResponse.json(
        { error: 'Forgejo sign-in is required to deploy Pages.' },
        { status: 401 },
      ),
      actor: 'anonymous',
    };
  }

  const token = controlToken();
  if (!token) {
    return {
      denied: NextResponse.json(
        { error: 'Pages deployment is not configured.' },
        { status: 503 },
      ),
      actor: session.username,
    };
  }
  const repoResponse = await fetch(
    `${FORGEJO_API}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
    {
      headers: { Accept: 'application/json', Authorization: `token ${token}` },
      cache: 'no-store',
    },
  );
  if (!repoResponse.ok) {
    return {
      denied: NextResponse.json(
        { error: 'Repository is unavailable.' },
        { status: 404 },
      ),
      actor: session.username,
    };
  }
  const repoInfo = await repoResponse.json() as {
    private?: boolean;
    default_branch?: string;
  };
  if (repoInfo.private) {
    return {
      denied: NextResponse.json(
        {
          error: 'NyankoFace Pages only publishes public repositories. Make the repository public before deploying.',
        },
        { status: 403 },
      ),
      actor: session.username,
    };
  }

  const branch = encodeURIComponent(repoInfo.default_branch || 'main');
  const permissionProbe = await fetch(
    `${FORGEJO_WEB}/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/_new/${branch}/`,
    {
      headers: { Cookie: cookie },
      cache: 'no-store',
      redirect: 'manual',
    },
  );
  if (permissionProbe.status === 302 || permissionProbe.status === 303) {
    return {
      denied: NextResponse.json(
        { error: 'Forgejo sign-in is required to deploy Pages.' },
        { status: 401 },
      ),
      actor: session.username,
    };
  }
  if (!permissionProbe.ok) {
    return {
      denied: NextResponse.json(
        { error: 'Write permission on this repository is required.' },
        { status: 403 },
      ),
      actor: session.username,
    };
  }
  return { denied: null, actor: session.username };
}

export function pagesRunnerUrl(owner: string, repo: string, action: 'status' | 'deploy'): string {
  return `${RUNNER_API}/pages/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${action}`;
}
