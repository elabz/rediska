import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// GET /api/core/evaluations?subject_type=&subject_id= - list evaluations for a subject
export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const search = request.nextUrl.search;

  try {
    const response = await fetch(`${CORE_API_URL}/evaluations${search}`, {
      method: 'GET',
      headers: { Cookie: `session=${sessionCookie.value}` },
    });
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error) {
    console.error('List evaluations error:', error);
    return NextResponse.json({ detail: 'Failed to list evaluations' }, { status: 500 });
  }
}

// POST /api/core/evaluations - record a human verdict
export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const body = await request.json();
    const response = await fetch(`${CORE_API_URL}/evaluations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session=${sessionCookie.value}`,
      },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Record evaluation error:', error);
    return NextResponse.json({ detail: 'Failed to record evaluation' }, { status: 500 });
  }
}
