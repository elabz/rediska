import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ watchId: string; runId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId, runId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const url = `${CORE_API_URL}/scout-watches/${watchId}/runs/${runId}`;

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
    console.error('Get scout watch run detail error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch scout watch run details' },
      { status: 500 }
    );
  }
}
