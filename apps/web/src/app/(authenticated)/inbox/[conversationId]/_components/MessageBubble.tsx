'use client';

import { useState } from 'react';
import { Loader2, ExternalLink, ImageIcon, MoreVertical, Trash2, RefreshCw, AlertTriangle, ShieldOff } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import type { Message } from '../_types';
import { getInitials, formatMessageTime } from '../_utils/timeFormat';
import { getSendErrorExplanation } from '../_utils/sendErrors';

export interface MessageBubbleProps {
  message: Message;
  counterpartUsername: string;
  redditComposeUrl?: string;
  onDelete?: (messageId: number) => void;
  onRetry?: (messageId: number) => void;
  onRemoteDelete?: (messageId: number) => void;
  isDeleting?: boolean;
  isRetrying?: boolean;
  isRemoteDeleting?: boolean;
}

export function MessageBubble({
  message,
  counterpartUsername,
  redditComposeUrl,
  onDelete,
  onRetry,
  onRemoteDelete,
  isDeleting,
  isRetrying,
  isRemoteDeleting,
}: MessageBubbleProps) {
  const isOutgoing = message.direction === 'out';
  const isSystem = message.direction === 'system';
  const [imageErrors, setImageErrors] = useState<Set<number>>(new Set());
  const isPending = message.remote_visibility === 'unknown';
  const isFailed = message.remote_visibility === 'send_failed';
  const canDelete = isOutgoing && (isPending || isFailed) && onDelete;
  const canRetry = isOutgoing && isFailed && onRetry;
  const canRemoteDelete = isOutgoing && message.remote_visibility === 'visible' && !!message.external_message_id && onRemoteDelete;

  const imageAttachments = (message.attachments || []).filter(att => att.mime_type.startsWith('image/'));

  if (isSystem) {
    return (
      <div className="flex justify-center my-4">
        <div className="bg-muted px-4 py-2 rounded-full text-sm text-muted-foreground">
          {message.body_text}
        </div>
      </div>
    );
  }

  return (
    <div className={cn(
      "flex gap-3 mb-4 group",
      isOutgoing ? "flex-row-reverse" : "flex-row"
    )}>
      {!isOutgoing && (
        <Avatar className="h-8 w-8 shrink-0">
          <AvatarFallback className="bg-muted text-xs">
            {getInitials(counterpartUsername)}
          </AvatarFallback>
        </Avatar>
      )}

      <div className={cn(
        "flex flex-col max-w-[75%]",
        isOutgoing ? "items-end" : "items-start"
      )}>
        {imageAttachments.length > 0 && (
          <div className={cn(
            "flex flex-wrap gap-2 mb-2",
            isOutgoing ? "justify-end" : "justify-start"
          )}>
            {imageAttachments.map((att) => (
              <div key={att.id} className="relative">
                {imageErrors.has(att.id) ? (
                  <div className="w-48 h-32 bg-muted rounded-lg flex items-center justify-center">
                    <div className="text-center text-muted-foreground">
                      <ImageIcon className="h-8 w-8 mx-auto mb-1" />
                      <span className="text-xs">Image unavailable</span>
                    </div>
                  </div>
                ) : (
                  <a
                    href={`/api/core/attachments/${att.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`/api/core/attachments/${att.id}`}
                      alt="Attachment"
                      className="max-w-[300px] max-h-[300px] rounded-lg object-contain cursor-pointer hover:opacity-90 transition-opacity"
                      style={{
                        width: att.width_px ? Math.min(att.width_px, 300) : 'auto',
                        height: att.height_px ? Math.min(att.height_px, 300) : 'auto',
                      }}
                      onError={() => setImageErrors(prev => { const next = new Set(prev); next.add(att.id); return next; })}
                    />
                  </a>
                )}
              </div>
            ))}
          </div>
        )}

        {message.body_text && (
          <div className={cn(
            "px-4 py-2.5 rounded-2xl",
            isOutgoing
              ? "bg-primary text-primary-foreground rounded-br-sm"
              : "bg-muted rounded-bl-sm"
          )}>
            <p className="text-sm whitespace-pre-wrap break-words">
              {message.body_text}
            </p>
          </div>
        )}

        <div className="flex items-center gap-2 mt-1 px-1">
          <span className="text-xs text-muted-foreground">
            {formatMessageTime(message.sent_at)}
          </span>
          {message.remote_visibility === 'unknown' && (
            <Badge variant="outline" className="text-xs h-5 px-1.5">
              Pending
            </Badge>
          )}
          {message.remote_visibility === 'send_failed' && (
            <Badge variant="destructive" className="text-xs h-5 px-1.5">
              <AlertTriangle className="h-3 w-3 mr-1" />
              Failed
            </Badge>
          )}
          {message.remote_visibility === 'deleted_by_author' && (
            <Badge variant="secondary" className="text-xs h-5 px-1.5">
              Deleted
            </Badge>
          )}

          {(canDelete || canRetry || canRemoteDelete || (isFailed && redditComposeUrl)) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0"
                  disabled={isDeleting || isRetrying || isRemoteDeleting}
                >
                  {(isDeleting || isRetrying || isRemoteDeleting) ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <MoreVertical className="h-3 w-3" />
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {canRetry && (
                  <DropdownMenuItem
                    onClick={() => onRetry(message.id)}
                  >
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Resend
                  </DropdownMenuItem>
                )}
                {isFailed && redditComposeUrl && (
                  <DropdownMenuItem asChild>
                    <a href={redditComposeUrl} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="h-4 w-4 mr-2" />
                      Send via Reddit
                    </a>
                  </DropdownMenuItem>
                )}
                {canRemoteDelete && (
                  <DropdownMenuItem
                    onClick={() => onRemoteDelete(message.id)}
                    className="text-destructive focus:text-destructive"
                  >
                    <ShieldOff className="h-4 w-4 mr-2" />
                    Delete from Reddit
                  </DropdownMenuItem>
                )}
                {canDelete && (
                  <DropdownMenuItem
                    onClick={() => onDelete(message.id)}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    Delete
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        {isFailed && message.send_error && (
          <div className="mt-1.5 px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/20 max-w-full">
            <p className="text-xs text-destructive">
              {getSendErrorExplanation(message.send_error)}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
