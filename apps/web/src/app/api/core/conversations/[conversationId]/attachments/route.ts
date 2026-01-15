import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(
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

    const formData = await request.formData();

    // Forward the file upload to the core API
    const response = await fetch(
      `${CORE_API_URL}/conversations/${conversationId}/attachments`,
      {
        method: 'POST',
        headers: {
          'Cookie': `session=${sessionCookie.value}`,
        },
        body: formData,
      }
    );

    if (!response.ok) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    console.error('Upload attachment proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to upload attachment' },
      { status: 503 }
    );
  }
}
