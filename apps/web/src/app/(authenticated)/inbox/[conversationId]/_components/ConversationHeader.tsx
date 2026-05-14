'use client';

import Link from 'next/link';
import { ArrowLeft, Download, ExternalLink, Send, ShieldOff, Star } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { ConversationDetail } from '../_types';
import { getInitials } from '../_utils/timeFormat';
import { ListsDropdown } from './ListsDropdown';

interface ConversationHeaderProps {
  conversation: ConversationDetail;
  conversationId: string;
  redditComposeUrl: string;
  scrubEligibleCount: number;
  onToggleStar: () => void;
  onScrubRequest: () => void;
}

export function ConversationHeader({
  conversation,
  conversationId,
  redditComposeUrl,
  scrubEligibleCount,
  onToggleStar,
  onScrubRequest,
}: ConversationHeaderProps) {
  const { counterpart } = conversation;

  return (
    <div className="flex items-center gap-4 p-4 border-b border-border shrink-0">
      <Link href="/inbox">
        <Button variant="ghost" size="icon">
          <ArrowLeft className="h-5 w-5" />
        </Button>
      </Link>

      <Avatar className="h-10 w-10">
        <AvatarFallback className="bg-primary/10 text-primary">
          {getInitials(counterpart.external_username)}
        </AvatarFallback>
      </Avatar>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold truncate">u/{counterpart.external_username}</span>
          {counterpart.remote_status === 'deleted' && (
            <Badge variant="secondary" className="text-xs">Deleted</Badge>
          )}
          {counterpart.remote_status === 'suspended' && (
            <Badge variant="destructive" className="text-xs">Suspended</Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {conversation.provider_id === 'reddit' ? 'Reddit' : conversation.provider_id}
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={onToggleStar}
          className={cn(
            "p-1.5 rounded transition-colors",
            counterpart.is_starred
              ? "text-yellow-500 hover:text-yellow-600"
              : "text-muted-foreground hover:text-foreground"
          )}
          title={counterpart.is_starred ? "Unstar" : "Star"}
        >
          <Star className={cn("h-5 w-5", counterpart.is_starred && "fill-current")} />
        </button>
        <ListsDropdown conversationId={conversationId} />
        <a
          href={`/api/core/conversations/${conversationId}/export`}
          download
          className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-xs"
          title="Export conversation as HTML"
        >
          <Download className="h-4 w-4" />
          <span className="hidden sm:inline">Export</span>
        </a>
        <a
          href={`https://reddit.com/u/${counterpart.external_username}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-xs"
          title="View Reddit profile"
        >
          <ExternalLink className="h-4 w-4" />
          <span className="hidden sm:inline">Full Profile</span>
        </a>
        {redditComposeUrl && (
          <a
            href={redditComposeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 text-xs"
            title="Send message via Reddit"
          >
            <Send className="h-4 w-4" />
            <span className="hidden sm:inline">Send via Reddit</span>
          </a>
        )}
        {scrubEligibleCount > 0 && (
          <button
            onClick={onScrubRequest}
            className="text-destructive/70 hover:text-destructive transition-colors flex items-center gap-1 text-xs"
            title="Delete all your messages from Reddit"
          >
            <ShieldOff className="h-4 w-4" />
            <span className="hidden sm:inline">Scrub</span>
          </button>
        )}
      </div>
    </div>
  );
}
