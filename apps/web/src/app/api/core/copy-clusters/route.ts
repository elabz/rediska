import { NextRequest } from 'next/server';
import { proxyToCore } from '../ban-list/proxy';

// GET /api/core/copy-clusters - List copy clusters (kind, decision, author, cursor)
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/copy-clusters', 'GET', 'Failed to fetch copy clusters');
}
