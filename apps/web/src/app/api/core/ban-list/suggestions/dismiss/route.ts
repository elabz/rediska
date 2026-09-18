import { NextRequest } from 'next/server';
import { proxyToCore } from '../../proxy';

// POST /api/core/ban-list/suggestions/dismiss - Dismiss one author's suggestion
export async function POST(request: NextRequest) {
  return proxyToCore(
    request,
    '/ban-list/suggestions/dismiss',
    'POST',
    'Failed to dismiss suggestion',
  );
}
