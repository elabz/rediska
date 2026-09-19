import { NextRequest } from 'next/server';
import { proxyToCore } from '../../ban-list/proxy';

type RouteParams = {
  params: Promise<{ clusterId: string }>;
};

// GET /api/core/copy-clusters/[clusterId] - Cluster members and what we hold per author
export async function GET(request: NextRequest, { params }: RouteParams) {
  const { clusterId } = await params;
  return proxyToCore(
    request,
    `/copy-clusters/${encodeURIComponent(clusterId)}`,
    'GET',
    'Failed to fetch copy cluster',
  );
}
