import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// POST /api/core/ops/calibration-reports/generate - Queue a calibration report now
export async function POST() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  try {
    const response = await fetch(`${CORE_API_URL}/ops/calibration-reports/generate`, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
      },
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error('Generate calibration report error:', error);
    return NextResponse.json(
      { detail: 'Failed to queue calibration report' },
      { status: 500 }
    );
  }
}
