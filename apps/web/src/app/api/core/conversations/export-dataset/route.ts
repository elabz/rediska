import { NextRequest, NextResponse } from 'next/server';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const sessionCookie = request.cookies.get('session');

    if (!sessionCookie) {
      return NextResponse.json(
        { detail: 'Not authenticated' },
        { status: 401 }
      );
    }

    // Forward all query params
    const searchParams = request.nextUrl.searchParams.toString();
    const url = `${CORE_API_URL}/conversations/export-dataset${searchParams ? `?${searchParams}` : ''}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Cookie': `session=${sessionCookie.value}`,
      },
    });

    if (!response.ok) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }

    const body = await response.text();
    const contentDisposition = response.headers.get('content-disposition') || 'attachment; filename="dataset.jsonl"';

    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': 'application/jsonl',
        'Content-Disposition': contentDisposition,
      },
    });
  } catch (error) {
    console.error('Export dataset proxy error:', error);
    return NextResponse.json(
      { detail: 'Failed to export dataset' },
      { status: 503 }
    );
  }
}
