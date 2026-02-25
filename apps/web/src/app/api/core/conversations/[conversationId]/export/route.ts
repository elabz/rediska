import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ conversationId: string }> }
) {
  try {
    const { conversationId } = await params;
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json(
        { detail: 'Not authenticated' },
        { status: 401 }
      );
    }

    const response = await fetch(
      `${CORE_API_URL}/conversations/${conversationId}/export`,
      {
        method: 'GET',
        headers: {
          'Cookie': `session=${sessionCookie.value}`,
        },
      }
    );

    if (!response.ok) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    const html = await response.text();
    const contentDisposition = response.headers.get('content-disposition') || 'attachment; filename="conversation.html"';

    return new NextResponse(html, {
      status: 200,
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Disposition': contentDisposition,
      },
    });
  } catch (error) {
    console.error('Export conversation proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to export conversation' },
      { status: 503 }
    );
  }
}
