import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { jobId } = await params;

  try {
    const response = await fetch(
      `${CORE_API_URL}/inbox/jobs/${encodeURIComponent(jobId)}`,
      {
        headers: {
          Cookie: `session=${sessionCookie.value}`,
        },
      }
    );

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Get transfer job status error:', error);
    return NextResponse.json({ detail: 'Failed to fetch job status' }, { status: 500 });
  }
}
