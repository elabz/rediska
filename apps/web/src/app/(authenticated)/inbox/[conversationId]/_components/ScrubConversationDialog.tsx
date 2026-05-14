'use client';

import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface ScrubConversationDialogProps {
  open: boolean;
  eligibleCount: number;
  isScrubbing: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ScrubConversationDialog({
  open,
  eligibleCount,
  isScrubbing,
  onCancel,
  onConfirm,
}: ScrubConversationDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Scrub this conversation?</DialogTitle>
          <DialogDescription>
            This will delete <strong>{eligibleCount}</strong> of your outgoing messages from Reddit. Local copies will be preserved but marked as deleted. This cannot be undone on Reddit.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isScrubbing}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isScrubbing}>
            {isScrubbing ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Scrubbing...
              </>
            ) : (
              `Scrub ${eligibleCount} messages`
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
