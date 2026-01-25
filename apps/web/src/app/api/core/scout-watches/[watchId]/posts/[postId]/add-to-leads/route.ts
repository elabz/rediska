import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

type RouteParams = {
  params: Promise<{ watchId: string; postId: string }>;
};

// POST /api/core/scout-watches/[watchId]/posts/[postId]/add-to-leads - Force add post to leads
export async function POST(request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { watchId, postId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${CORE_API_URL}/scout-watches/${watchId}/posts/${postId}/add-to-leads`,
      {
        method: 'POST',
        headers: {
          Cookie: `session=${sessionCookie.value}`,
        },
      }
    );

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Add post to leads error:', error);
    return NextResponse.json(
      { detail: 'Failed to add post to leads' },
      { status: 500 }
    );
  }
}
