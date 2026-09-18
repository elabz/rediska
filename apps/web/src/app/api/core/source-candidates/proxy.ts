import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

/**
 * Forward a source-candidates request to the core API with the session cookie.
 * Shared by the /api/core/source-candidates/* route handlers.
 */
export async function proxyToCore(
  request: NextRequest,
  path: string,
  method: 'GET' | 'POST',
  errorMessage: string,
): Promise<NextResponse> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const queryString = request.nextUrl.searchParams.toString();
  const url = `${CORE_API_URL}${path}${queryString ? `?${queryString}` : ''}`;

  try {
    const init: RequestInit = {
      method,
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session=${sessionCookie.value}`,
      },
    };
    if (method === 'POST') {
      const body = await request.text();
      init.body = body || '{}';
    }

    const response = await fetch(url, init);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error(`${errorMessage}:`, error);
    return NextResponse.json({ detail: errorMessage }, { status: 500 });
  }
}
