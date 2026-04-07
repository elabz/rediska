import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ listId: string }> }
) {
  try {
    const { listId } = await params;
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const body = await request.json();
    const response = await fetch(`${CORE_API_URL}/lists/${listId}`, {
      method: 'PUT',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Update list proxy error:', error);
    return NextResponse.json({ detail: 'Failed to update list' }, { status: 503 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ listId: string }> }
) {
  try {
    const { listId } = await params;
    const sessionCookie = request.cookies.get('session');
    if (!sessionCookie) {
      return NextResponse.json({ detail: 'Not authenticated' }, { status: 401 });
    }

    const response = await fetch(`${CORE_API_URL}/lists/${listId}`, {
      method: 'DELETE',
      headers: { 'Cookie': `session=${sessionCookie.value}` },
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Delete list proxy error:', error);
    return NextResponse.json({ detail: 'Failed to delete list' }, { status: 503 });
  }
}
