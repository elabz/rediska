import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// POST /api/core/leads/[leadId]/analyze - Trigger lead analysis
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leadId: string }> }
) {
  const { leadId } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(`${CORE_API_URL}/leads/${leadId}/analyze`, {
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
    console.error('Analyze lead error:', error);
    return NextResponse.json(
      { detail: 'Failed to analyze lead' },
      { status: 500 }
    );
  }
}
