import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// GET /api/core/evaluations/vocabulary
export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const search = request.nextUrl.search;

  try {
    const response = await fetch(`${CORE_API_URL}/evaluations/vocabulary${search}`, {
      method: 'GET',
      headers: { Cookie: `session=${sessionCookie.value}` },
    });
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error) {
    console.error('Evaluations vocabulary error:', error);
    return NextResponse.json({ detail: 'Failed to load evaluations vocabulary' }, { status: 500 });
  }
}
