import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const response = await fetch(`${CORE_API_URL}/lists`, {
      headers: { 'Cookie': `session=${sessionCookie.value}` },
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Lists proxy error:', error);
    return NextResponse.json({ detail: 'Failed to fetch lists' }, { status: 503 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();
    const response = await fetch(`${CORE_API_URL}/lists`, {
      method: 'POST',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Create list proxy error:', error);
    return NextResponse.json({ detail: 'Failed to create list' }, { status: 503 });
  }
}
