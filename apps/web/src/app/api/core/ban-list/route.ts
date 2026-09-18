import { NextRequest } from 'next/server';
import { proxyToCore } from './proxy';

// GET /api/core/ban-list - List ban entries (status, source, q, cursor)
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/ban-list', 'GET', 'Failed to fetch ban list');
}

// POST /api/core/ban-list - Ban a username
export async function POST(request: NextRequest) {
  return proxyToCore(request, '/ban-list', 'POST', 'Failed to ban account');
}
