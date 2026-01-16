import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

type RouteParams = {
  params: Promise<{ watchId: string }>;
};

// GET /api/core/scout-watches/[watchId]/runs - Get run history
export async function GET(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  // Get query params (limit)
  const searchParams = request.nextUrl.searchParams;
  const queryString = searchParams.toString();
  const url = `${CORE_API_URL}/scout-watches/${watchId}/runs${queryString ? `?${queryString}` : ''}`;

  try {
    const response = await fetch(url, {
      headers: {
        Cookie: `session=${sessionCookie.value}`,
      },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Get scout watch runs error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch scout watch runs' },
      { status: 500 }
    );
  }
}
