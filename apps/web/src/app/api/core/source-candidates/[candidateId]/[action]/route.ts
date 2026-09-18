import { NextRequest, NextResponse } from 'next/server';
import { proxyToCore } from '../../proxy';

const ACTIONS = new Set(['dismiss', 'restore', 'snooze', 'accept', 'trial']);

type RouteParams = {
  params: Promise<{ candidateId: string; action: string }>;
};

// POST /api/core/source-candidates/[candidateId]/(dismiss|restore|snooze|accept|trial)
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { candidateId, action } = await params;
  if (!ACTIONS.has(action)) {
    return NextResponse.json({ detail: `Unknown action: ${action}` }, { status: 404 });
  }
  return proxyToCore(
    request,
    `/source-candidates/${encodeURIComponent(candidateId)}/${action}`,
    'POST',
    `Failed to ${action} candidate`,
  );
}
