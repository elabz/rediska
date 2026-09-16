'use client';

import { useState } from 'react';
import { ClipboardCheck, ListChecks, BarChart3, Download, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { DIMENSION_LABELS, EVALUABLE_DIMENSIONS } from '@/lib/evaluations';

import { ReviewQueue } from './components/ReviewQueue';
import { EvaluationDashboard } from './components/EvaluationDashboard';

type Tab = 'queue' | 'dashboard';

export default function EvaluationsPage() {
  const [tab, setTab] = useState<Tab>('queue');
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportDataset = async (dimension: string | null) => {
    const key = dimension ?? 'final';
    setExporting(key);
    setExportError(null);
    try {
      const url = dimension
        ? `/api/core/evaluations/export?dimension=${encodeURIComponent(dimension)}`
        : '/api/core/evaluations/export';
      const response = await fetch(url, { credentials: 'include' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : 'Export failed');
      }
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `evaluations_${key}.jsonl`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-500/10">
            <ClipboardCheck className="h-5 w-5 text-teal-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Evaluations</h1>
            <p className="text-muted-foreground">
              Judge the agents&rsquo; decisions, then measure which prompts deserve to stay
            </p>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" disabled={exporting !== null}>
              {exporting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Download className="h-4 w-4 mr-1" />}
              Export JSONL
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Labelled dataset</DropdownMenuLabel>
            <DropdownMenuItem onClick={() => exportDataset(null)}>{DIMENSION_LABELS.final}</DropdownMenuItem>
            <DropdownMenuSeparator />
            {EVALUABLE_DIMENSIONS.map((d) => (
              <DropdownMenuItem key={d} onClick={() => exportDataset(d)}>
                {DIMENSION_LABELS[d]}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {exportError && (
        <div className="rounded-lg border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          {exportError}
        </div>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList>
          <TabsTrigger value="queue">
            <ListChecks className="h-4 w-4 mr-2" />
            Review queue
          </TabsTrigger>
          <TabsTrigger value="dashboard">
            <BarChart3 className="h-4 w-4 mr-2" />
            Dashboard
          </TabsTrigger>
        </TabsList>
        <TabsContent value="queue" className="mt-4">
          <ReviewQueue />
        </TabsContent>
        <TabsContent value="dashboard" className="mt-4">
          <EvaluationDashboard onGoToQueue={() => setTab('queue')} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
