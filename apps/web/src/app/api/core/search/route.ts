import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();

    const response = await fetch(`${CORE_API_URL}/search`, {
      method: 'POST',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Search proxy error:', error);
    return NextResponse.json(
      { detail: 'Search failed' },
      { status: 503 }
    );
  }
}
