import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

type RouteParams = {
  params: Promise<{ postId: string }>;
};

// POST /api/core/scout-watches/posts/[postId]/dismiss - Dismiss a needs-review post
export async function POST(_request: NextRequest, { params }: RouteParams) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');
  const { postId } = await params;

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(`${CORE_API_URL}/scout-watches/posts/${postId}/dismiss`, {
      method: 'POST',
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
    console.error('Dismiss post error:', error);
    return NextResponse.json(
      { detail: 'Failed to dismiss post' },
      { status: 500 }
    );
  }
}
