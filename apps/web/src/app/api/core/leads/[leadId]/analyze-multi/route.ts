import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// Extend timeout for long-running multi-agent analysis
export const maxDuration = 600; // 10 minutes

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leadId: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { leadId } = await params;

  // Parse request body for options
  let regenerateSummaries = false;
  try {
    const body = await request.json();
    regenerateSummaries = body.regenerate_summaries ?? false;
  } catch {
    // Empty body is OK, use defaults
  }

  // Build URL with query parameter
  const url = `${CORE_API_URL}/leads/${leadId}/analyze-multi?regenerate_summaries=${regenerateSummaries}`;

  try {
    // Long timeout for multi-agent analysis (10 minutes)
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 600000);

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Multi-agent analysis error:', error);
    return NextResponse.json(
      { detail: 'Failed to run multi-agent analysis' },
      { status: 500 }
    );
  }
}
