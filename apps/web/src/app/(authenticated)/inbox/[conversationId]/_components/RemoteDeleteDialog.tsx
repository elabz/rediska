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

interface RemoteDeleteDialogProps {
  messageId: number | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: (messageId: number) => void;
}

export function RemoteDeleteDialog({ messageId, isDeleting, onCancel, onConfirm }: RemoteDeleteDialogProps) {
  return (
    <Dialog open={messageId !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete from Reddit?</DialogTitle>
          <DialogDescription>
            This will delete this message from Reddit. Your local copy will be preserved but marked as deleted. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isDeleting}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => messageId !== null && onConfirm(messageId)}
            disabled={isDeleting}
          >
            {isDeleting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Deleting...
              </>
            ) : (
              'Delete from Reddit'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
