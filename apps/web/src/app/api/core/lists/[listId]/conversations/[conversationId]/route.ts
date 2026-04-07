import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ listId: string; conversationId: string }> }
) {
  try {
    const { listId, conversationId } = await params;
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const response = await fetch(
      `${CORE_API_URL}/lists/${listId}/conversations/${conversationId}`,
      {
        method: 'POST',
        headers: { 'Cookie': `session=${sessionCookie.value}` },
      }
    );

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Add to list proxy error:', error);
    return NextResponse.json({ detail: 'Failed to add to list' }, { status: 503 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ listId: string; conversationId: string }> }
) {
  try {
    const { listId, conversationId } = await params;
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const response = await fetch(
      `${CORE_API_URL}/lists/${listId}/conversations/${conversationId}`,
      {
        method: 'DELETE',
        headers: { 'Cookie': `session=${sessionCookie.value}` },
      }
    );

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Remove from list proxy error:', error);
    return NextResponse.json({ detail: 'Failed to remove from list' }, { status: 503 });
  }
}
