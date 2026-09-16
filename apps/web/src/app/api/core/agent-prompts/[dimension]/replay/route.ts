import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// POST /api/core/agent-prompts/[dimension]/replay - replay a draft/version against labelled cases
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ dimension: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { dimension } = await params;

  try {
    const body = await request.json();
    const response = await fetch(`${CORE_API_URL}/agent-prompts/${dimension}/replay`, {
      method: 'POST',
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
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Start replay error:', error);
    return NextResponse.json({ detail: 'Failed to start replay' }, { status: 500 });
  }
}
