import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ filename: string }> }
) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const { filename } = await params;

  try {
    const response = await fetch(
      `${CORE_API_URL}/inbox/exports/${encodeURIComponent(filename)}`,
      {
        headers: {
          Cookie: `session=${sessionCookie.value}`,
        },
      }
    );

    if (!response.ok) {
      const data = await response.json().catch(() => ({ detail: 'Download failed' }));
      return NextResponse.json(data, { status: response.status });
    }

    // Stream the dump straight through; these files can be large.
    return new NextResponse(response.body, {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
        'Content-Disposition': `attachment; filename="${filename}"`,
      },
    });
  } catch (error) {
    console.error('Download inbox export error:', error);
    return NextResponse.json({ detail: 'Failed to download export' }, { status: 500 });
  }
}
