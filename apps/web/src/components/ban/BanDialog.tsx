'use client';

import { useEffect, useState } from 'react';
import { AlertCircle, Ban, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import {
  REASON_LABELS,
  REASON_PRESETS,
  createBan,
  type BanCreateResponse,
  type ReasonPreset,
} from '@/lib/banList';

export interface BanDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  username: string;
  providerId?: string;
  /** Preselected reason (e.g. `copy_ring` from a cluster view). */
  initialReason?: ReasonPreset;
  onBanned?: (result: BanCreateResponse) => void;
}

/** Ban one username: a reason is required, notes are optional. */
export function BanDialog({
  open,
  onOpenChange,
  username,
  providerId = 'reddit',
  initialReason,
  onBanned,
}: BanDialogProps) {
  const [reason, setReason] = useState<ReasonPreset | null>(initialReason ?? null);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setReason(initialReason ?? null);
      setNotes('');
      setError(null);
    }
  }, [open, initialReason]);

  const submit = async () => {
    if (!reason) {
      setError('Choose a reason');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await createBan({
        username,
        reason,
        notes: notes.trim() || null,
        provider_id: providerId,
      });
      onBanned?.(result);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to ban');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Ban u/{username}</DialogTitle>
          <DialogDescription>
            No message can be sent to a banned account and their open leads move to Ignored.
            Nothing is deleted; lifting the ban restores the leads.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Reason</Label>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Reason">
              {REASON_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  role="radio"
                  aria-checked={reason === preset}
                  onClick={() => setReason(preset)}
                  className={cn(
                    'rounded-md border px-3 py-1.5 text-sm transition-colors',
                    reason === preset
                      ? 'border-destructive bg-destructive/10 text-destructive'
                      : 'border-border text-muted-foreground hover:text-foreground',
                  )}
                >
                  {REASON_LABELS[preset]}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ban-notes">Notes (optional)</Label>
            <Textarea
              id="ban-notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What happened"
            />
          </div>

          {error && (
            <p className="flex items-center gap-2 text-sm text-destructive" role="alert">
              <AlertCircle className="h-4 w-4" />
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={submit} disabled={saving || !reason}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />}
            Ban
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
