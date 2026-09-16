import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// GET /api/core/evaluations/export?dimension= - stream the labelled dataset (JSONL)
export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const search = request.nextUrl.search;

  try {
    const response = await fetch(`${CORE_API_URL}/evaluations/export${search}`, {
      method: 'GET',
      headers: { Cookie: `session=${sessionCookie.value}` },
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({ detail: 'Export failed' }));
      return NextResponse.json(data, { status: response.status });
    }

    const headers = new Headers();
    headers.set('Content-Type', response.headers.get('content-type') || 'application/x-ndjson');
    const disposition = response.headers.get('content-disposition');
    if (disposition) headers.set('Content-Disposition', disposition);

    return new NextResponse(response.body, { status: 200, headers });
  } catch (error) {
    console.error('Export evaluations error:', error);
    return NextResponse.json({ detail: 'Failed to export evaluations' }, { status: 500 });
  }
}
