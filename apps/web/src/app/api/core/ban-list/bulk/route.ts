import { NextRequest } from 'next/server';
import { proxyToCore } from '../proxy';

// POST /api/core/ban-list/bulk - Ban a copy cluster's authors as one batch
export async function POST(request: NextRequest) {
  return proxyToCore(request, '/ban-list/bulk', 'POST', 'Failed to bulk ban');
}
