import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

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
  const url = `${CORE_API_URL}/agent-prompts/${dimension}/rollback`;

  try {
    const body = await request.json();

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Rollback prompt error:', error);
    return NextResponse.json(
      { detail: 'Failed to rollback prompt' },
      { status: 500 }
    );
  }
}
