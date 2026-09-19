import { NextRequest } from 'next/server';
import { proxyToCore } from '../../../ban-list/proxy';

type RouteParams = {
  params: Promise<{ clusterId: string }>;
};

// POST /api/core/copy-clusters/[clusterId]/decision - Record a human decision
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { clusterId } = await params;
  return proxyToCore(
    request,
    `/copy-clusters/${encodeURIComponent(clusterId)}/decision`,
    'POST',
    'Failed to record cluster decision',
  );
}
