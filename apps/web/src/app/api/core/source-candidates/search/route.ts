import { NextRequest } from 'next/server';
import { proxyToCore } from '../proxy';

// GET /api/core/source-candidates/search?q= - Provider location search
export async function GET(request: NextRequest) {
  return proxyToCore(request, '/source-candidates/search', 'GET', 'Location search failed');
}
