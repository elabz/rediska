import { NextRequest } from 'next/server';
import { proxyToCore } from '../../proxy';

type RouteParams = {
  params: Promise<{ banId: string }>;
};

// POST /api/core/ban-list/[banId]/lift - Lift a ban
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { banId } = await params;
  return proxyToCore(
    request,
    `/ban-list/${encodeURIComponent(banId)}/lift`,
    'POST',
    'Failed to lift ban',
  );
}
