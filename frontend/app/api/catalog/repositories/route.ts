import { NextRequest, NextResponse } from 'next/server';
import { getCatalogPage, parseCatalogQuery } from '@/lib/catalog-sort';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams;
    const query = parseCatalogQuery({
      topic: params.get('topic') || undefined,
      q: params.get('q') || undefined,
      sort: params.get('sort') || undefined,
      order: params.get('order') || undefined,
      page: params.get('page') || undefined,
      limit: params.get('limit') || undefined,
    });
    const result = await getCatalogPage(query);
    return NextResponse.json(result, { status: result.ok ? 200 : 503 });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Invalid catalog query' },
      { status: 400 },
    );
  }
}
