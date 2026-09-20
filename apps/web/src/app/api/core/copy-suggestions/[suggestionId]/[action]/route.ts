import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// Only these two decisions exist; anything else is not proxied.
const ACTIONS = new Set(['accept', 'reject']);

// POST /api/core/copy-suggestions/{id}/{accept|reject}
export async function POST(
  request: Request,
  { params }: { params: Promise<{ suggestionId: string; action: string }> }
) {
  const { suggestionId, action } = await params;

  if (!ACTIONS.has(action)) {
    return NextResponse.json({ detail: 'Unknown action' }, { status: 404 });
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(
      `${CORE_API_URL}/copy-suggestions/${suggestionId}/${action}`,
      {
        method: 'POST',
        headers: { Cookie: `session=${sessionCookie.value}` },
      }
    );

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Copy suggestion decision error:', error);
    return NextResponse.json(
      { detail: 'Failed to record the decision' },
      { status: 500 }
    );
  }
}
