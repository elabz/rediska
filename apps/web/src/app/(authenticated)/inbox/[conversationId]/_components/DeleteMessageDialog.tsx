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

interface DeleteMessageDialogProps {
  messageId: number | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: (messageId: number) => void;
}

export function DeleteMessageDialog({ messageId, isDeleting, onCancel, onConfirm }: DeleteMessageDialogProps) {
  return (
    <Dialog open={messageId !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete Message?</DialogTitle>
          <DialogDescription>
            This will permanently delete this pending message. This action cannot be undone.
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
              'Delete'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
