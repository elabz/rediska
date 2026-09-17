'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import Link from 'next/link';
import {
  Loader2,
  Download,
  Upload,
  Trash2,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
  ArrowLeft,
  FileJson,
  RefreshCw,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

/** Phrase the backend requires before it will run a clear. Must match exactly. */
const CLEAR_CONFIRMATION_PHRASE = 'CLEAR MY INBOX';

const POLL_INTERVAL_MS = 1500;

interface ExportFileInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
}

interface TransferJobStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  stage?: string | null;
  done?: number | null;
  total?: number | null;
  percent?: number | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

type OperationKind = 'export' | 'import' | 'clear';

interface Operation {
  kind: OperationKind;
  jobId: string;
  status: TransferJobStatus | null;
}

// =============================================================================
// Helpers
// =============================================================================

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

const OPERATION_LABELS: Record<OperationKind, string> = {
  export: 'Export',
  import: 'Import',
  clear: 'Clear',
};

// =============================================================================
// Progress display (task 6.4)
// =============================================================================

function ProgressPanel({ operation }: { operation: Operation }) {
  const { kind, status } = operation;
  const label = OPERATION_LABELS[kind];

  if (!status) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Queuing {label.toLowerCase()}…</span>
      </div>
    );
  }

  if (status.status === 'failed') {
    return (
      <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
        <div>
          <p className="font-medium text-destructive">{label} failed</p>
          <p className="mt-1 break-all text-muted-foreground">{status.error}</p>
        </div>
      </div>
    );
  }

  if (status.status === 'completed') {
    const result = status.result ?? {};
    const warnings = result.warnings as { missing_files?: string[] } | undefined;
    const missing = warnings?.missing_files ?? [];
    const rejected = result.status === 'rejected';

    if (rejected) {
      return (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div>
            <p className="font-medium text-destructive">{label} rejected</p>
            <p className="mt-1 text-muted-foreground">{String(result.error)}</p>
          </div>
        </div>
      );
    }

    return (
      <div className="space-y-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">
        <div className="flex items-center gap-2">
          <CheckCircle className="h-4 w-4 text-emerald-500" />
          <p className="font-medium">{label} complete</p>
        </div>
        <pre className="overflow-x-auto rounded bg-background/60 p-2 text-xs">
          {JSON.stringify(result, null, 2)}
        </pre>
        {missing.length > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-amber-500">
            <AlertTriangle className="h-3.5 w-3.5" />
            {missing.length} referenced attachment file
            {missing.length === 1 ? '' : 's'} missing on disk
          </p>
        )}
      </div>
    );
  }

  const percent = status.percent ?? 0;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {label} in progress
          {status.stage ? ` — ${status.stage}` : ''}
        </span>
        <span className="tabular-nums text-muted-foreground">
          {status.done != null && status.total != null
            ? `${status.done} / ${status.total}`
            : `${percent.toFixed(0)}%`}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
    </div>
  );
}

// =============================================================================
// Page
// =============================================================================

export default function InboxBackupPage() {
  const [operation, setOperation] = useState<Operation | null>(null);
  const [exports, setExports] = useState<ExportFileInfo[]>([]);
  const [loadingExports, setLoadingExports] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [importFile, setImportFile] = useState<File | null>(null);
  const [clearConfirmation, setClearConfirmation] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const busy = operation != null && operation.status?.status !== 'completed'
    && operation.status?.status !== 'failed';

  // -- data ------------------------------------------------------------

  const loadExports = useCallback(async () => {
    setLoadingExports(true);
    try {
      const response = await fetch('/api/core/inbox/exports');
      if (!response.ok) throw new Error('Failed to load exports');
      const data = await response.json();
      setExports(data.exports ?? []);
    } catch (err) {
      console.error(err);
      setError('Could not load the list of dump files.');
    } finally {
      setLoadingExports(false);
    }
  }, []);

  useEffect(() => {
    loadExports();
  }, [loadExports]);

  // Poll the active job until it settles.
  useEffect(() => {
    if (!operation) return;
    const settled =
      operation.status?.status === 'completed' || operation.status?.status === 'failed';
    if (settled) return;

    const timer = setInterval(async () => {
      try {
        const response = await fetch(`/api/core/inbox/jobs/${operation.jobId}`);
        if (!response.ok) return;
        const status: TransferJobStatus = await response.json();
        setOperation((current) =>
          current && current.jobId === status.job_id ? { ...current, status } : current
        );
        if (status.status === 'completed' && operation.kind === 'export') {
          loadExports();
        }
      } catch (err) {
        console.error('Poll failed', err);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [operation, loadExports]);

  // -- actions ---------------------------------------------------------

  const startExport = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch('/api/core/inbox/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Failed to queue export');
      setOperation({ kind: 'export', jobId: data.job_id, status: null });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to queue export');
    }
  }, []);

  const startImport = useCallback(async () => {
    if (!importFile) return;
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', importFile);

      const response = await fetch('/api/core/inbox/import', {
        method: 'POST',
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Failed to queue import');

      setOperation({ kind: 'import', jobId: data.job_id, status: null });
      setImportFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to queue import');
    }
  }, [importFile]);

  const startClear = useCallback(async () => {
    setError(null);
    try {
      const response = await fetch('/api/core/inbox/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmation: clearConfirmation }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? 'Failed to queue clear');

      setOperation({ kind: 'clear', jobId: data.job_id, status: null });
      setClearConfirmation('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to queue clear');
    }
  }, [clearConfirmation]);

  // -- render ----------------------------------------------------------

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="space-y-2">
        <Link
          href="/ops"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Operations
        </Link>
        <h1 className="text-2xl font-semibold">Inbox Backup &amp; Restore</h1>
        <p className="text-sm text-muted-foreground">
          Export the inbox to a portable dump file, restore from one, or clear the inbox.
          Dumps record attachment <em>references</em>, not file content — the files
          themselves stay on disk.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p>{error}</p>
        </div>
      )}

      {operation && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {OPERATION_LABELS[operation.kind]} job
            </CardTitle>
            <CardDescription className="font-mono text-xs">{operation.jobId}</CardDescription>
          </CardHeader>
          <CardContent>
            <ProgressPanel operation={operation} />
          </CardContent>
        </Card>
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Export                                                            */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Download className="h-4 w-4" />
            Export
          </CardTitle>
          <CardDescription>
            Dump all conversations, messages, and attachment metadata to a JSON file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <Button onClick={startExport} disabled={busy}>
              {busy && operation?.kind === 'export' ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Download className="mr-2 h-4 w-4" />
              )}
              Start export
            </Button>
            <Button variant="outline" onClick={loadExports} disabled={loadingExports}>
              <RefreshCw className={cn('mr-2 h-4 w-4', loadingExports && 'animate-spin')} />
              Refresh
            </Button>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">Available dumps</p>
            {loadingExports ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : exports.length === 0 ? (
              <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
                No dump files yet. Run an export to create one.
              </p>
            ) : (
              <ul className="divide-y rounded-md border">
                {exports.map((item) => (
                  <li
                    key={item.filename}
                    className="flex items-center justify-between gap-3 p-3 text-sm"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <FileJson className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0">
                        <p className="truncate font-medium">{item.filename}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatDate(item.created_at)} · {formatBytes(item.size_bytes)}
                        </p>
                      </div>
                    </div>
                    <Button asChild variant="outline" size="sm">
                      <a
                        href={`/api/core/inbox/exports/${encodeURIComponent(item.filename)}`}
                        download={item.filename}
                      >
                        <Download className="mr-2 h-3.5 w-3.5" />
                        Download
                      </a>
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Import                                                            */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Upload className="h-4 w-4" />
            Import
          </CardTitle>
          <CardDescription>
            Restore from a dump file. The restore is atomic and skips content that already
            exists, so re-importing the same dump is safe.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
            disabled={busy}
          />
          {importFile && (
            <p className="text-xs text-muted-foreground">
              Selected: {importFile.name} ({formatBytes(importFile.size)})
            </p>
          )}
          <Button onClick={startImport} disabled={busy || !importFile}>
            {busy && operation?.kind === 'import' ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            Start import
          </Button>
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Clear                                                             */}
      {/* ---------------------------------------------------------------- */}
      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-destructive">
            <Trash2 className="h-4 w-4" />
            Clear inbox
            <Badge variant="outline" className="border-destructive/40 text-destructive">
              Destructive
            </Badge>
          </CardTitle>
          <CardDescription>
            Deletes every conversation, message, and message-linked attachment record.
            Providers, identities, credentials, contacts, leads, and profile data are kept,
            and attachment files stay on disk — so a dump taken beforehand restores
            everything.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <p>
              Export first. This cannot be undone except by importing a dump you already
              have.
            </p>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="clear-confirmation" className="text-sm font-medium">
              Type <code className="rounded bg-muted px-1 py-0.5">{CLEAR_CONFIRMATION_PHRASE}</code> to
              confirm
            </label>
            <Input
              id="clear-confirmation"
              value={clearConfirmation}
              onChange={(event) => setClearConfirmation(event.target.value)}
              placeholder={CLEAR_CONFIRMATION_PHRASE}
              disabled={busy}
              autoComplete="off"
            />
          </div>
          <Button
            variant="destructive"
            onClick={startClear}
            disabled={busy || clearConfirmation !== CLEAR_CONFIRMATION_PHRASE}
          >
            {busy && operation?.kind === 'clear' ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="mr-2 h-4 w-4" />
            )}
            Clear inbox
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
