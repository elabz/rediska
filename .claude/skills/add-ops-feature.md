# Add New Ops Feature

When adding a new operation to the Ops page, follow this checklist to ensure all layers are properly connected.

## Architecture Overview

```
UI (ops/page.tsx) → Next.js Proxy (api/core/ops/.../route.ts) → FastAPI Backend (ops.py)
```

The UI never calls the Python backend directly. All requests go through Next.js proxy routes.

## Step-by-Step Process

### 1. Verify Backend Endpoint Exists

Check `services/core/rediska_core/api/routes/ops.py` for the endpoint.

Example endpoint structure:
```python
@router.post(
    "/feature/action",
    response_model=FeatureResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Description of the feature",
)
async def trigger_feature(
    request: FeatureRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    # Implementation
```

### 2. Create Next.js Proxy Route

Create directory and route file:
```
apps/web/src/app/api/core/ops/{feature}/{action}/route.ts
```

Use this template (copy from existing route like `backfill/conversations/route.ts`):

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const CORE_API_URL = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('session');

  if (!sessionCookie) {
    return NextResponse.json({ detail: 'Unauthorized' }, { status: 401 });
  }

  const url = `${CORE_API_URL}/ops/{feature}/{action}`;

  try {
    const body = await request.json().catch(() => ({}));

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Cookie: `session=${sessionCookie.value}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error) {
    console.error('Feature action error:', error);
    return NextResponse.json(
      { detail: 'Failed to trigger feature' },
      { status: 500 }
    );
  }
}
```

### 3. Add UI Component to Ops Page

Edit `apps/web/src/app/(authenticated)/ops/page.tsx`:

#### a. Add Interface
```typescript
interface FeatureResult {
  status: 'idle' | 'running' | 'success' | 'error';
  message: string;
  jobId?: string;
}
```

#### b. Add State Hook
```typescript
const [featureResult, setFeatureResult] = useState<FeatureResult>({
  status: 'idle',
  message: '',
});
```

#### c. Add Trigger Function with Polling
```typescript
const triggerFeature = async () => {
  setFeatureResult({
    status: 'running',
    message: 'Starting feature...',
  });

  try {
    const response = await fetch('/api/core/ops/feature/action', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ /* params */ }),
    });

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'Failed to start feature');
    }

    const data = await response.json();
    const jobId = data.job_id;

    setFeatureResult({
      status: 'running',
      message: 'Processing...',
      jobId,
    });

    // Poll for job completion using /api/core/ops/backfill/{jobId}
    // (reuses the generic Celery job status endpoint)
    const pollInterval = 2000;
    const maxPolls = 120;
    let polls = 0;

    const checkStatus = async (): Promise<void> => {
      if (polls >= maxPolls) {
        setFeatureResult({
          status: 'running',
          message: 'Taking longer than expected. Continuing in background.',
          jobId,
        });
        return;
      }

      try {
        const statusResponse = await fetch(`/api/core/ops/backfill/${jobId}`, {
          credentials: 'include',
        });

        if (!statusResponse.ok) {
          throw new Error('Failed to check status');
        }

        const statusData = await statusResponse.json();

        if (statusData.status === 'success') {
          setFeatureResult({
            status: 'success',
            message: 'Completed successfully',
            jobId,
          });
        } else if (statusData.status === 'failure') {
          setFeatureResult({
            status: 'error',
            message: statusData.result?.error || 'Failed',
            jobId,
          });
        } else {
          polls++;
          setTimeout(checkStatus, pollInterval);
        }
      } catch {
        setFeatureResult({
          status: 'error',
          message: 'Failed to check status',
          jobId,
        });
      }
    };

    setTimeout(checkStatus, pollInterval);
  } catch (err) {
    setFeatureResult({
      status: 'error',
      message: err instanceof Error ? err.message : 'Failed',
    });
  }
};
```

#### d. Add Card Component
```tsx
<Card>
  <CardHeader>
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-{color}-500/10">
        <IconName className="h-5 w-5 text-{color}-500" />
      </div>
      <div>
        <CardTitle className="text-lg">Feature Name</CardTitle>
        <CardDescription>Brief description</CardDescription>
      </div>
    </div>
  </CardHeader>
  <CardContent className="space-y-4">
    <p className="text-sm text-muted-foreground">
      Longer explanation of what this feature does.
    </p>

    <Button
      onClick={triggerFeature}
      disabled={featureResult.status === 'running'}
      className="w-full"
      size="lg"
      variant="secondary"
    >
      {featureResult.status === 'running' ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          Processing...
        </>
      ) : (
        <>
          <IconName className="h-4 w-4 mr-2" />
          Trigger Feature
        </>
      )}
    </Button>

    {featureResult.status !== 'idle' && (
      <div className={cn(
        "rounded-lg p-4",
        featureResult.status === 'running'
          ? 'bg-blue-500/10 border border-blue-500/20'
          : featureResult.status === 'success'
            ? 'bg-emerald-500/10 border border-emerald-500/20'
            : 'bg-destructive/10 border border-destructive/20'
      )}>
        {/* Status icon and message */}
      </div>
    )}
  </CardContent>
</Card>
```

### 4. Rebuild and Deploy

```bash
docker compose build rediska-web && docker compose up -d rediska-web
```

## Quick Verification

After building, check the Next.js build output for your new route:
```
├ ƒ /api/core/ops/{feature}/{action}    0 B    0 B
```

If the route is missing, the proxy file wasn't created correctly.
