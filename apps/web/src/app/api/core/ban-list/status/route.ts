import { NextRequest } from 'next/server';
import { proxyToCore } from '../proxy';

// GET /api/core/ban-list/status?username= - Ban state of one username
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/ban-list/status', 'GET', 'Failed to fetch ban status');
}
