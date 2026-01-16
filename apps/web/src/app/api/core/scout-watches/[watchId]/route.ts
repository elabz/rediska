import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

type RouteParams = {
  params: Promise<{ watchId: string }>;
};

// GET /api/core/scout-watches/[watchId] - Get a single watch
export async function GET(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(`${CORE_API_URL}/scout-watches/${watchId}`, {
      headers: {
        Cookie: `session=${sessionCookie.value}`,
      },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Get scout watch error:', error);
    return NextResponse.json(
      { detail: 'Failed to fetch scout watch' },
      { status: 500 }
    );
  }
}

// PUT /api/core/scout-watches/[watchId] - Update a watch
export async function PUT(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const body = await request.json();

    const response = await fetch(`${CORE_API_URL}/scout-watches/${watchId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `session=${sessionCookie.value}`,
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Update scout watch error:', error);
    return NextResponse.json(
      { detail: 'Failed to update scout watch' },
      { status: 500 }
    );
  }
}

// DELETE /api/core/scout-watches/[watchId] - Delete a watch
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(`${CORE_API_URL}/scout-watches/${watchId}`, {
      method: 'DELETE',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
      },
    });

    if (response.status === 204) {
      return new NextResponse(null, { status: 204 });
    }

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Delete scout watch error:', error);
    return NextResponse.json(
      { detail: 'Failed to delete scout watch' },
      { status: 500 }
    );
  }
}
