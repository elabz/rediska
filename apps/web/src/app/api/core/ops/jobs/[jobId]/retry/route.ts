import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { jobId } = await params;
  const url = `${CORE_API_URL}/ops/jobs/${jobId}/retry`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Retry job error:', error);
    return NextResponse.json(
      { detail: 'Failed to retry job' },
      { status: 500 }
    );
  }
}
