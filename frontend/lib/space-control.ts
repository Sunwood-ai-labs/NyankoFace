import 'server-only';

import fs from 'fs';
import { NextRequest, NextResponse } from 'next/server';

const FORGEJO_API = process.env.FORGEJO_API || 'http://forgejo:3000/api/v1';
const FORGEJO_WEB = process.env.FORGEJO_WEB || 'http://forgejo:3000';
const FORGEJO_TOKEN_FILE = process.env.FORGEJO_TOKEN_FILE || '/shared/token';
export const RUNNER_API = (process.env.RUNNER_API || 'http://spaces-runner:8000/api').replace(/\/$/, '');

export function controlToken(): string | null {
  try {
    return fs.readFileSync(FORGEJO_TOKEN_FILE, 'utf8').trim() || null;
  } catch {
    return null;
  }
}

async function forgejoFetch(path: string) {
  return fetch(`${FORGEJO_API}${path}`, {
    headers: { Accept: 'application/json', Authorization: `token ${controlToken()}` },
    cache: 'no-store',
  });
}

async function publicSpace(
  owner: string,
  repo: string,
): Promise<{ denied: Response | null; defaultBranch: string }> {
  const repoResponse = await forgejoFetch(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`);
  if (!repoResponse.ok) {
    return {
      denied: NextResponse.json({ error: 'Repository is unavailable.' }, { status: 404 }),
      defaultBranch: 'main',
    };
  }

  const repoInfo = await repoResponse.json() as {
    private?: boolean;
    default_branch?: string;
    topics?: string[];
  };
  if (repoInfo.private) {
    return {
      denied: NextResponse.json({ error: 'Private Spaces cannot be started anonymously.' }, { status: 403 }),
      defaultBranch: repoInfo.default_branch || 'main',
    };
  }
  if (!repoInfo.topics?.includes('space')) {
    return {
      denied: NextResponse.json({ error: 'Repository is not a Space.' }, { status: 404 }),
      defaultBranch: repoInfo.default_branch || 'main',
    };
  }
  return { denied: null, defaultBranch: repoInfo.default_branch || 'main' };
}

export async function canStartPublicSpace(
  owner: string,
  repo: string,
): Promise<Response | null> {
  return (await publicSpace(owner, repo)).denied;
}

export async function canControlSpace(
  request: NextRequest,
  owner: string,
  repo: string,
): Promise<Response | null> {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie) return NextResponse.json({ error: 'Forgejo sign-in is required.' }, { status: 401 });

  const { denied, defaultBranch } = await publicSpace(owner, repo);
  if (denied) return denied;
  const branch = encodeURIComponent(defaultBranch);
  const permissionProbe = await fetch(
    `${FORGEJO_WEB}/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/_new/${branch}/`,
    { headers: { Cookie: cookie }, cache: 'no-store', redirect: 'manual' },
  );
  if (permissionProbe.status === 303 || permissionProbe.status === 302) {
    return NextResponse.json({ error: 'Forgejo sign-in is required.' }, { status: 401 });
  }
  if (!permissionProbe.ok) {
    return NextResponse.json({ error: 'Write permission on this Space is required.' }, { status: 403 });
  }
  return null;
}

export async function canControlRepository(
  request: NextRequest,
  owner: string,
  repo: string,
): Promise<Response | null> {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie) {
    return NextResponse.json({ error: 'Forgejo sign-in is required.' }, { status: 401 });
  }
  const repoResponse = await forgejoFetch(
    `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
  );
  if (!repoResponse.ok) {
    return NextResponse.json({ error: 'Repository is unavailable.' }, { status: 404 });
  }
  const repoInfo = await repoResponse.json() as { default_branch?: string };
  const branch = encodeURIComponent(repoInfo.default_branch || 'main');
  const permissionProbe = await fetch(
    `${FORGEJO_WEB}/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/_new/${branch}/`,
    { headers: { Cookie: cookie }, cache: 'no-store', redirect: 'manual' },
  );
  if (permissionProbe.status === 303 || permissionProbe.status === 302) {
    return NextResponse.json({ error: 'Forgejo sign-in is required.' }, { status: 401 });
  }
  if (!permissionProbe.ok) {
    return NextResponse.json(
      { error: 'Write permission on this repository is required.' },
      { status: 403 },
    );
  }
  return null;
}

export async function controlActor(request: NextRequest): Promise<string> {
  const cookie = request.headers.get('cookie') || '';
  if (!cookie) return 'authorized-forgejo-user';
  try {
    const response = await fetch(`${FORGEJO_WEB}/api/v1/user`, {
      headers: { Accept: 'application/json', Cookie: cookie },
      cache: 'no-store',
    });
    if (!response.ok) return 'authorized-forgejo-user';
    const user = await response.json() as { login?: string };
    return user.login?.trim() || 'authorized-forgejo-user';
  } catch {
    return 'authorized-forgejo-user';
  }
}

export function runnerHeaders(actor = 'authorized-forgejo-user'): HeadersInit | null {
  const token = controlToken();
  if (!token) return null;
  return {
    'X-NyankoFace-Control-Token': token,
    'X-NyankoFace-Actor': actor,
  };
}

export async function postNativeForgejoAction(
  request: NextRequest,
  publicPath: string,
): Promise<Response> {
  if (!publicPath.startsWith('/git/')) {
    return new Response(
      JSON.stringify({ error: 'Invalid native Forgejo action path.' }),
      {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }
  const cookie = request.headers.get('cookie') || '';
  if (!cookie) {
    return new Response(
      JSON.stringify({ error: 'Forgejo sign-in is required.' }),
      {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  }
  return fetch(`${FORGEJO_WEB}${publicPath.slice('/git'.length)}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Cookie: cookie,
    },
    cache: 'no-store',
    redirect: 'manual',
  });
}

