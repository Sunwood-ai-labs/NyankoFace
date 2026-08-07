import { NextRequest } from 'next/server';
import { proxyMcpAdmin } from '@/lib/mcp-admin';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Context) {
  const { path } = await context.params;
  return proxyMcpAdmin(request, path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
