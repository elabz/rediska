import { NextRequest } from 'next/server';
import { proxyToCore } from './proxy';

// GET /api/core/source-candidates - List source candidates
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/source-candidates', 'GET', 'Failed to fetch source candidates');
}

// POST /api/core/source-candidates - Add a location as a manual candidate
export async function POST(request: NextRequest) {
  return proxyToCore(request, '/source-candidates', 'POST', 'Failed to add candidate');
}
