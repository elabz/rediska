import { NextRequest } from 'next/server';
import { proxyToCore } from '../proxy';

type RouteParams = {
  params: Promise<{ candidateId: string }>;
};

// GET /api/core/source-candidates/[candidateId] - One candidate
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { candidateId } = await params;
  return proxyToCore(
    request,
    `/source-candidates/${encodeURIComponent(candidateId)}`,
    'GET',
    'Failed to fetch candidate',
  );
}
