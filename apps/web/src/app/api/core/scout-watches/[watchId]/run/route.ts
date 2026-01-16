import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

type RouteParams = {
  params: Promise<{ watchId: string }>;
};

// POST /api/core/scout-watches/[watchId]/run - Trigger a manual run
export async function POST(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${CORE_API_URL}/scout-watches/${watchId}/run`,
      {
        method: 'POST',
        headers: {
          Cookie: `session=${sessionCookie.value}`,
        },
      }
    );

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Trigger scout watch run error:', error);
    return NextResponse.json(
      { detail: 'Failed to trigger scout watch run' },
      { status: 500 }
    );
  }
}
