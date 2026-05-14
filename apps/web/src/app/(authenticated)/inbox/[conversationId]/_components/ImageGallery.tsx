'use client';

import { ChevronUp, ChevronDown, Images } from 'lucide-react';
import type { GalleryImage } from '../_types';

interface ImageGalleryProps {
  images: GalleryImage[];
  expanded: boolean;
  onToggle: () => void;
}

export function ImageGallery({ images, expanded, onToggle }: ImageGalleryProps) {
  if (images.length === 0) return null;

  return (
    <div className="border-b border-border">
      <button
        onClick={onToggle}
        className="w-full px-4 py-2 flex items-center justify-between hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Images className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            {images.length} image{images.length !== 1 ? 's' : ''}
          </span>
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 max-h-64 overflow-y-auto">
          <div className="flex flex-wrap gap-2">
            {images.map(({ attachment: att }) => (
              <a
                key={att.id}
                href={`/api/core/attachments/${att.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block shrink-0"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/core/attachments/${att.id}`}
                  alt="Gallery image"
                  className="h-20 w-20 object-cover rounded-md hover:opacity-80 transition-opacity"
                />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
