'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, Loader2, Paperclip, Send } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { Counterpart, Message } from '../_types';
import { clearDraft, readDraft, writeDraft, type DraftValue } from '../_utils/drafts';

interface ComposeBoxProps {
  conversationId: string;
  counterpart: Counterpart;
  identityId: number | null;
  onSent: (optimisticMessage: Message) => void;
}

export function ComposeBox({ conversationId, counterpart, identityId, onSent }: ComposeBoxProps) {
  const [messageText, setMessageText] = useState(() => readDraft(conversationId).text);
  const [attachmentIds, setAttachmentIds] = useState<number[]>(() => readDraft(conversationId).attachmentIds);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Persist the in-progress message draft (text + uploaded attachment IDs) to
  // localStorage so accidental back-navigation does not destroy typed content
  // or orphan uploaded files. Debounced to avoid a write per keystroke;
  // flushes synchronously on unmount.
  useEffect(() => {
    const value: DraftValue = { text: messageText, attachmentIds };
    const timer = setTimeout(() => {
      writeDraft(conversationId, value);
    }, 400);
    return () => {
      clearTimeout(timer);
      writeDraft(conversationId, value);
    };
  }, [conversationId, messageText, attachmentIds]);

  const isRecipientUnsendable = counterpart.remote_status === 'deleted' || counterpart.remote_status === 'suspended';

  const sendMessage = useCallback(async () => {
    if (!messageText.trim() || sending) return;

    setSending(true);
    setSendError(null);

    try {
      const response = await fetch(
        `/api/core/conversations/${conversationId}/messages`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            body_text: messageText.trim(),
            attachment_ids: attachmentIds.length > 0 ? attachmentIds : undefined,
          }),
        }
      );

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to send message');
      }

      const result = await response.json();

      const optimisticMessage: Message = {
        id: result.message_id,
        direction: 'out',
        body_text: messageText.trim(),
        sent_at: new Date().toISOString(),
        remote_visibility: 'unknown',
        send_error: null,
        identity_id: identityId,
        created_at: new Date().toISOString(),
      };

      onSent(optimisticMessage);
      setMessageText('');
      clearDraft(conversationId);
      setAttachmentIds([]);
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setSending(false);
    }
  }, [messageText, sending, conversationId, identityId, attachmentIds, onSent]);

  const handleAttachmentSelect = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploadingAttachment(true);
    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(
          `/api/core/conversations/${conversationId}/attachments`,
          {
            method: 'POST',
            credentials: 'include',
            body: formData,
          }
        );

        if (!response.ok) {
          const data = await response.json();
          setSendError(data.detail || `Failed to upload ${file.name}`);
          continue;
        }

        const data = await response.json();
        setAttachmentIds(prev => [...prev, data.attachment_id]);
      }
    } catch (err) {
      setSendError(err instanceof Error ? err.message : 'Failed to upload attachment');
    } finally {
      setUploadingAttachment(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, [conversationId]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Plain Enter inserts a newline; only Cmd+Enter (Ctrl+Enter off macOS) sends.
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendMessage();
    }
  }, [sendMessage]);

  return (
    <div className="p-4 border-t border-border shrink-0">
      {sendError && (
        <div className="mb-2 p-2 bg-destructive/10 text-destructive text-sm rounded-md flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{sendError}</span>
          <button onClick={() => setSendError(null)} className="ml-auto text-xs underline">
            Dismiss
          </button>
        </div>
      )}
      <div className="flex gap-2 max-w-full">
        <Textarea
          value={messageText}
          onChange={(e) => setMessageText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isRecipientUnsendable
              ? `Cannot send to ${counterpart.remote_status} user`
              : 'Type a message... (Cmd+Enter to send)'
          }
          className="min-h-[44px] resize-y flex-1 min-w-0"
          disabled={sending || isRecipientUnsendable}
          rows={7}
        />
        <div className="flex gap-1 shrink-0">
          <Button
            size="icon"
            variant="ghost"
            className="h-11 w-11"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadingAttachment || sending}
            title="Attach files"
          >
            {uploadingAttachment ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Paperclip className="h-4 w-4" />
            )}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx"
            className="hidden"
            onChange={(e) => handleAttachmentSelect(e.target.files)}
            disabled={uploadingAttachment || sending}
          />
          <Button
            size="icon"
            className="shrink-0 h-11 w-11"
            onClick={sendMessage}
            disabled={!messageText.trim() || sending || isRecipientUnsendable}
            title={sending ? 'Sending...' : 'Send message'}
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {attachmentIds.length > 0 && (
        <div className="mt-2 p-2 bg-muted rounded-md">
          <p className="text-xs font-medium text-muted-foreground mb-1">
            {attachmentIds.length} attachment{attachmentIds.length !== 1 ? 's' : ''} attached
          </p>
          <div className="flex gap-1 flex-wrap">
            {attachmentIds.map((id) => (
              <Badge key={id} variant="secondary" className="text-xs">
                Attachment #{id}
                <button
                  onClick={() => setAttachmentIds(prev => prev.filter(aid => aid !== id))}
                  className="ml-1 hover:text-destructive"
                >
                  ✕
                </button>
              </Badge>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground mt-2 text-center">
        Messages are queued and sent in the background
      </p>
    </div>
  );
}
