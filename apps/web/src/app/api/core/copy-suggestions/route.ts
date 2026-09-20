import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// GET /api/core/copy-suggestions - probable rewrites awaiting a decision
export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const queryString = request.nextUrl.searchParams.toString();
  const url = `${CORE_API_URL}/copy-suggestions${queryString ? `?${queryString}` : ''}`;

  try {
    const response = await fetch(url, {
      headers: { Cookie: `session=${sessionCookie.value}` },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Copy suggestions error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch copy suggestions' },
      { status: 500 }
    );
  }
}
