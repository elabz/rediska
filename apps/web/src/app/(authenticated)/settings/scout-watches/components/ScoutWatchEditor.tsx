'use client';

import { useState } from 'react';
import { ArrowLeft, Loader2, Save } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { ScoutWatch } from '../page';

interface ScoutWatchEditorProps {
  watch: ScoutWatch | null; // null = create new
  onClose: () => void;
  onSaved: () => void;
}

const SORT_OPTIONS = [
  { value: 'new', label: 'New' },
  { value: 'hot', label: 'Hot' },
  { value: 'top', label: 'Top' },
  { value: 'rising', label: 'Rising' },
  { value: 'relevance', label: 'Relevance (search only)' },
];

const TIME_FILTER_OPTIONS = [
  { value: 'hour', label: 'Past Hour' },
  { value: 'day', label: 'Past Day' },
  { value: 'week', label: 'Past Week' },
  { value: 'month', label: 'Past Month' },
  { value: 'year', label: 'Past Year' },
  { value: 'all', label: 'All Time' },
];

export function ScoutWatchEditor({ watch, onClose, onSaved }: ScoutWatchEditorProps) {
  const isNew = !watch;

  const [sourceLocation, setSourceLocation] = useState(watch?.source_location || '');
  const [searchQuery, setSearchQuery] = useState(watch?.search_query || '');
  const [sortBy, setSortBy] = useState(watch?.sort_by || 'new');
  const [timeFilter, setTimeFilter] = useState(watch?.time_filter || 'day');
  const [autoAnalyze, setAutoAnalyze] = useState(watch?.auto_analyze ?? true);
  const [minConfidence, setMinConfidence] = useState(watch?.min_confidence ?? 0.7);
  const [isActive, setIsActive] = useState(watch?.is_active ?? true);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!sourceLocation.trim()) {
      setError('Source location is required');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const payload: Record<string, unknown> = {
        source_location: sourceLocation.trim(),
        search_query: searchQuery.trim() || null,
        sort_by: sortBy,
        time_filter: timeFilter,
        auto_analyze: autoAnalyze,
        min_confidence: minConfidence,
        is_active: isActive,
      };

      const url = isNew
        ? '/api/core/scout-watches'
        : `/api/core/scout-watches/${watch.id}`;

      const response = await fetch(url, {
        method: isNew ? 'POST' : 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to save watch');
      }

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-4">
        <Button variant="ghost" size="icon" onClick={onClose}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <CardTitle>{isNew ? 'Create Scout Watch' : 'Edit Scout Watch'}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {error && (
          <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
            {error}
          </div>
        )}

        {/* Source Location */}
        <div className="space-y-2">
          <Label htmlFor="source-location">Subreddit</Label>
          <Input
            id="source-location"
            placeholder="r/r4r"
            value={sourceLocation}
            onChange={(e) => setSourceLocation(e.target.value)}
            disabled={!isNew} // Can't change location after creation
          />
          <p className="text-xs text-muted-foreground">
            The subreddit to monitor (e.g., r/r4r, r/ForeverAloneDating)
          </p>
        </div>

        {/* Search Query */}
        <div className="space-y-2">
          <Label htmlFor="search-query">Search Query (optional)</Label>
          <Input
            id="search-query"
            placeholder="looking for AND dom"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Reddit search syntax. Use AND, OR, NOT for complex queries.
          </p>
        </div>

        {/* Sort and Time Filter */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Sort By</Label>
            <Select value={sortBy} onValueChange={setSortBy}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Time Filter</Label>
            <Select value={timeFilter} onValueChange={setTimeFilter}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIME_FILTER_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Auto Analyze */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label>Auto-Analyze Posts</Label>
            <p className="text-xs text-muted-foreground">
              Run quick analysis on new posts using Meta-Analysis agent
            </p>
          </div>
          <Switch checked={autoAnalyze} onCheckedChange={setAutoAnalyze} />
        </div>

        {/* Min Confidence */}
        {autoAnalyze && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Minimum Confidence</Label>
              <span className="text-sm font-medium">{(minConfidence * 100).toFixed(0)}%</span>
            </div>
            <Slider
              value={[minConfidence]}
              onValueChange={([v]) => setMinConfidence(v)}
              min={0}
              max={1}
              step={0.05}
            />
            <p className="text-xs text-muted-foreground">
              Only create leads for posts with confidence above this threshold
            </p>
          </div>
        )}

        {/* Active Status */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label>Active</Label>
            <p className="text-xs text-muted-foreground">
              Run this watch on the 5-minute schedule
            </p>
          </div>
          <Switch checked={isActive} onCheckedChange={setIsActive} />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-4">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Saving...
              </>
            ) : (
              <>
                <Save className="h-4 w-4 mr-2" />
                {isNew ? 'Create Watch' : 'Save Changes'}
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
