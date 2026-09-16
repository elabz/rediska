import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// GET /api/core/agent-prompts/[dimension]/replays/[replayId] - replay detail with per-case rows
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ dimension: string; replayId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { dimension, replayId } = await params;

  try {
    const response = await fetch(
      `${CORE_API_URL}/agent-prompts/${dimension}/replays/${replayId}`,
      { method: 'GET', headers: { Cookie: `session=${sessionCookie.value}` } }
    );
    const data = await response.json();
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error) {
    console.error('Get replay error:', error);
    return NextResponse.json({ detail: 'Failed to get replay' }, { status: 500 });
  }
}
