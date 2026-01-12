import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const response = await fetch(`${CORE_API_URL}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    // Extract session cookie from core service response
    const setCookieHeader = response.headers.get('set-cookie');

    // Create the Next.js response
    const nextResponse = NextResponse.json(data, { status: response.status });

    if (setCookieHeader) {
      // Parse the session value from the Set-Cookie header
      const sessionMatch = setCookieHeader.match(/session=([^;]+)/);
      if (sessionMatch) {
        const sessionValue = sessionMatch[1];

        // Set the cookie properly for the browser
        // Using the cookies() API ensures proper handling
        nextResponse.cookies.set('session', sessionValue, {
          httpOnly: true,
          secure: true,
          sameSite: 'lax',
          path: '/',
          maxAge: 7 * 24 * 60 * 60, // 1 week
        });
      }
    }

    return nextResponse;
  } catch (error) {
    console.error('Login proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to connect to authentication service' },
      { status: 503 }
    );
  }
}
