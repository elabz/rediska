import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    // Forward the multipart body as-is. Rebuilding FormData here would buffer
    // the whole dump in memory; passing the parsed form through keeps the
    // boundary handling in one place.
    const formData = await request.formData();

    const response = await fetch(`${CORE_API_URL}/inbox/import`, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
      },
      body: formData,
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Trigger inbox import error:', error);
    return NextResponse.json({ detail: 'Failed to queue import' }, { status: 500 });
  }
}
