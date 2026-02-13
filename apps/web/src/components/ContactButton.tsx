'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface ContactButtonProps {
  username: string;
  providerId?: string;
  variant?: 'button' | 'dropdown-item' | 'icon';
  size?: 'sm' | 'default' | 'lg' | 'icon';
  className?: string;
  onError?: (error: string) => void;
}

export function ContactButton({
  username,
  providerId = 'reddit',
  variant = 'button',
  size = 'sm',
  className,
  onError,
}: ContactButtonProps) {
  const router = useRouter();
  const [isContacting, setIsContacting] = useState(false);

  const cleanUsername = username.replace(/^u\//, '');

  const handleContact = useCallback(async (e?: React.MouseEvent) => {
    e?.stopPropagation();
    e?.preventDefault();

    if (isContacting || !cleanUsername) return;

    setIsContacting(true);

    try {
      const response = await fetch('/api/core/conversations/initiate/by-username', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: cleanUsername, provider_id: providerId }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to initiate conversation');
      }

      const conversation = await response.json();
      router.push(`/inbox/${conversation.id}`);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to contact user';
      onError?.(errorMsg);
      console.error('Failed to initiate conversation:', err);
    } finally {
      setIsContacting(false);
    }
  }, [cleanUsername, providerId, isContacting, onError, router]);

  if (variant === 'dropdown-item') {
    return (
      <DropdownMenuItem
        onClick={handleContact}
        disabled={isContacting}
        className={className}
      >
        {isContacting ? (
          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
        ) : (
          <MessageSquare className="h-4 w-4 mr-2" />
        )}
        Contact
      </DropdownMenuItem>
    );
  }

  if (variant === 'icon') {
    return (
      <Button
        variant="ghost"
        size="icon"
        onClick={handleContact}
        disabled={isContacting}
        className={cn('h-6 w-6', className)}
        title={`Message u/${cleanUsername}`}
      >
        {isContacting ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <MessageSquare className="h-3 w-3" />
        )}
      </Button>
    );
  }

  // Default button variant
  return (
    <Button
      variant="outline"
      size={size}
      onClick={handleContact}
      disabled={isContacting}
      className={className}
      title={`Message u/${cleanUsername}`}
    >
      {isContacting ? (
        <Loader2 className="h-4 w-4 animate-spin mr-1" />
      ) : (
        <MessageSquare className="h-4 w-4 mr-1" />
      )}
      Contact
    </Button>
  );
}
