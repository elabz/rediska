import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leadId: string }> }
) {
  try {
    const { leadId } = await params;
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json(
        { detail: 'Not authenticated' },
        { status: 401 }
      );
    }

    const response = await fetch(
      `${CORE_API_URL}/conversations/initiate/from-lead/${leadId}`,
      {
        method: 'POST',
        headers: {
          'Cookie': `session=${sessionCookie.value}`,
        },
      }
    );

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Initiate conversation from lead proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to initiate conversation' },
      { status: 503 }
    );
  }
}
