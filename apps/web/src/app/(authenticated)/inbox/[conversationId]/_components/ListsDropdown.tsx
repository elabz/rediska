'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, List, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useConversationLists } from '../_hooks/useConversationLists';

interface ListsDropdownProps {
  conversationId: string;
}

export function ListsDropdown({ conversationId }: ListsDropdownProps) {
  const { lists, memberOf, loading, toggle, createAndAdd } = useConversationLists(conversationId);
  const [open, setOpen] = useState(false);
  const [newListName, setNewListName] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleCreate = async () => {
    await createAndAdd(newListName);
    setNewListName('');
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "p-1.5 rounded transition-colors text-muted-foreground hover:text-foreground",
          memberOf.size > 0 && "text-blue-500"
        )}
        title="Manage lists"
      >
        <List className="h-5 w-5" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 w-56 bg-popover border rounded-md shadow-lg z-50 p-1">
          {lists.length === 0 && (
            <p className="text-xs text-muted-foreground px-2 py-1.5">No lists yet</p>
          )}
          {lists.map(lst => (
            <button
              key={lst.id}
              onClick={() => toggle(lst.id)}
              className="w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded hover:bg-muted transition-colors text-left"
            >
              <span className={cn("h-4 w-4 flex items-center justify-center rounded border", memberOf.has(lst.id) ? "bg-primary border-primary text-primary-foreground" : "border-muted-foreground/30")}>
                {memberOf.has(lst.id) && <Check className="h-3 w-3" />}
              </span>
              <span className="truncate flex-1">{lst.name}</span>
              <span className="text-xs text-muted-foreground">{lst.conversation_count}</span>
            </button>
          ))}
          <div className="border-t mt-1 pt-1">
            <div className="flex items-center gap-1 px-1">
              <input
                type="text"
                value={newListName}
                onChange={(e) => setNewListName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                placeholder="New list..."
                className="flex-1 text-sm border rounded px-2 py-1 bg-background"
              />
              <button
                onClick={handleCreate}
                disabled={!newListName.trim() || loading}
                className="p-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
