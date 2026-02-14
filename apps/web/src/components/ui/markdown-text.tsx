'use client';

import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';

interface MarkdownTextProps {
  children: string;
  className?: string;
}

/**
 * Renders markdown text with styled output.
 * Used for LLM-generated reasoning, summaries, etc.
 */
export function MarkdownText({ children, className }: MarkdownTextProps) {
  return (
    <div className={cn('max-w-none text-foreground', className)}>
      <ReactMarkdown
        components={{
          p: ({ children: c }) => <p className="my-1 leading-relaxed">{c}</p>,
          ul: ({ children: c }) => <ul className="my-1 ml-4 list-disc space-y-0.5">{c}</ul>,
          ol: ({ children: c }) => <ol className="my-1 ml-4 list-decimal space-y-0.5">{c}</ol>,
          li: ({ children: c }) => <li className="text-sm">{c}</li>,
          strong: ({ children: c }) => <strong className="font-semibold">{c}</strong>,
          h1: ({ children: c }) => <h1 className="text-base font-bold mt-2 mb-1">{c}</h1>,
          h2: ({ children: c }) => <h2 className="text-sm font-bold mt-2 mb-1">{c}</h2>,
          h3: ({ children: c }) => <h3 className="text-sm font-semibold mt-1.5 mb-0.5">{c}</h3>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
