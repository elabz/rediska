import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ attachmentId: string }> }
) {
  try {
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const { attachmentId } = await params;
    const url = `${CORE_API_URL}/attachments/${attachmentId}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
      },
    });

    if (!response.ok) {
      return NextResponse.json(
        { detail: 'Failed to fetch attachment' },
        { status: response.status }
      );
    }

    // Get the content type and body
    const contentType = response.headers.get('Content-Type') || 'application/octet-stream';
    const data = await response.arrayBuffer();

    return new NextResponse(data, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=31536000, immutable',
      },
    });
  } catch (error) {
    console.error('Attachment proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch attachment' },
      { status: 503 }
    );
  }
}
