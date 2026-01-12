import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const url = `${CORE_API_URL}/ops/jobs/counts`;

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
    console.error('Get job counts error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch job counts' },
      { status: 500 }
    );
  }
}
