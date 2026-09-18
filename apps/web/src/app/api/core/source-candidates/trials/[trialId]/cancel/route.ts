import { NextRequest } from 'next/server';
import { proxyToCore } from '../../../proxy';

type RouteParams = {
  params: Promise<{ trialId: string }>;
};

// POST /api/core/source-candidates/trials/[trialId]/cancel - Cancel a trial
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { trialId } = await params;
  return proxyToCore(
    request,
    `/source-candidates/trials/${encodeURIComponent(trialId)}/cancel`,
    'POST',
    'Failed to cancel trial',
  );
}
