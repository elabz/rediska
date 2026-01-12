import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    // Forward query parameters
    const searchParams = request.nextUrl.searchParams;
    const url = `${CORE_API_URL}/audit?${searchParams.toString()}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Audit proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch audit logs' },
      { status: 503 }
    );
  }
}
