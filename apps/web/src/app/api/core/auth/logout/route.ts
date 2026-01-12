import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  try {
    // Get session cookie from the request
    const sessionCookie = request.cookies.get('session');

    if (sessionCookie) {
      // Forward the logout request to core
      await fetch(`${CORE_API_URL}/auth/logout`, {
        method: 'POST',
        headers: {
          'Cookie': `session=${sessionCookie.value}`,
        },
      });
    }

    // Clear the session cookie
    const response = NextResponse.json({ success: true, message: 'Logged out successfully' });
    response.cookies.delete('session');

    return response;
  } catch (error) {
    console.error('Logout proxy error:', error);
    // Still clear the cookie even if core request fails
    const response = NextResponse.json({ success: true, message: 'Logged out' });
    response.cookies.delete('session');
    return response;
  }
}
