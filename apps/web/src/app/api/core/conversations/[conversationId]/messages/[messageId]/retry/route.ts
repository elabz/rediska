import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ conversationId: string; messageId: string }> }
) {
  try {
    const { conversationId, messageId } = await params;
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json(
        { detail: 'Not authenticated' },
        { status: 401 }
      );
    }

    const response = await fetch(
      `${CORE_API_URL}/conversations/${conversationId}/messages/${messageId}/retry`,
      {
        method: 'POST',
        headers: {
          'Cookie': `session=${sessionCookie.value}`,
        },
      }
    );

    if (!response.ok) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 202 });
  } catch (error) {
    console.error('Retry message proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to retry message' },
      { status: 503 }
    );
  }
}
