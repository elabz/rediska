import { NextRequest } from 'next/server';
import { proxyToCore } from '../proxy';

// GET /api/core/ban-list/suggestions - Copy-ring authors suggested for a ban
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/ban-list/suggestions', 'GET', 'Failed to fetch ban suggestions');
}
