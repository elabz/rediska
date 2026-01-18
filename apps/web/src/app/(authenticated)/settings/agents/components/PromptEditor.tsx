'use client';

import { useState } from 'react';
import {
  ArrowLeft,
  Save,
  Loader2,
  AlertCircle,
  User,
  Heart,
  Target,
  AlertTriangle,
  Flame,
  Sparkles,
  History,
  Settings,
  Search,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

import { VersionHistory } from './VersionHistory';
import type { AgentPrompt } from '../page';

interface PromptEditorProps {
  dimension: string;
  prompt: AgentPrompt;
  onClose: () => void;
  onSaved: () => void;
}

const AGENT_CONFIG: Record<string, {
  title: string;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}> = {
  demographics: {
    title: 'Demographics',
    icon: <User className="h-5 w-5" />,
    color: 'text-blue-500',
    bgColor: 'bg-blue-500/10',
  },
  preferences: {
    title: 'Preferences & Interests',
    icon: <Heart className="h-5 w-5" />,
    color: 'text-pink-500',
    bgColor: 'bg-pink-500/10',
  },
  relationship_goals: {
    title: 'Relationship Goals',
    icon: <Target className="h-5 w-5" />,
    color: 'text-purple-500',
    bgColor: 'bg-purple-500/10',
  },
  risk_flags: {
    title: 'Risk Assessment',
    icon: <AlertTriangle className="h-5 w-5" />,
    color: 'text-amber-500',
    bgColor: 'bg-amber-500/10',
  },
  sexual_preferences: {
    title: 'Intimacy & Compatibility',
    icon: <Flame className="h-5 w-5" />,
    color: 'text-red-500',
    bgColor: 'bg-red-500/10',
  },
  meta_analysis: {
    title: 'Meta-Analysis Coordinator',
    icon: <Sparkles className="h-5 w-5" />,
    color: 'text-emerald-500',
    bgColor: 'bg-emerald-500/10',
  },
  scout_quick_analysis: {
    title: 'Scout Quick Analysis',
    icon: <Search className="h-5 w-5" />,
    color: 'text-cyan-500',
    bgColor: 'bg-cyan-500/10',
  },
};

export function PromptEditor({ dimension, prompt, onClose, onSaved }: PromptEditorProps) {
  const [systemPrompt, setSystemPrompt] = useState(prompt.system_prompt);
  const [temperature, setTemperature] = useState(prompt.temperature);
  const [maxTokens, setMaxTokens] = useState(prompt.max_tokens);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  const config = AGENT_CONFIG[dimension];

  const handlePromptChange = (value: string) => {
    setSystemPrompt(value);
    setHasChanges(value !== prompt.system_prompt || temperature !== prompt.temperature || maxTokens !== prompt.max_tokens);
  };

  const handleTemperatureChange = (value: number) => {
    setTemperature(value);
    setHasChanges(systemPrompt !== prompt.system_prompt || value !== prompt.temperature || maxTokens !== prompt.max_tokens);
  };

  const handleMaxTokensChange = (value: number) => {
    setMaxTokens(value);
    setHasChanges(systemPrompt !== prompt.system_prompt || temperature !== prompt.temperature || value !== prompt.max_tokens);
  };

  const handleSave = async () => {
    if (!hasChanges && !notes) {
      setError('No changes to save');
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const response = await fetch(`/api/core/agent-prompts/${dimension}`, {
        method: 'PUT',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          system_prompt: systemPrompt,
          temperature,
          max_tokens: maxTokens,
          notes: notes || `Updated ${config?.title || dimension} prompt`,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to save prompt');
      }

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleRollback = () => {
    // Refresh after rollback
    onSaved();
  };

  if (!config) {
    return (
      <Card className="p-8">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
          <p className="text-destructive">Unknown agent dimension: {dimension}</p>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="border-b">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={onClose}>
              <ArrowLeft className="h-4 w-4 mr-1" />
              Back
            </Button>
            <div className={cn(
              'flex h-10 w-10 items-center justify-center rounded-lg',
              config.bgColor
            )}>
              <span className={config.color}>{config.icon}</span>
            </div>
            <div>
              <CardTitle className="text-lg">{config.title}</CardTitle>
              <div className="flex items-center gap-2 mt-1">
                <Badge variant="secondary" className="text-xs">
                  v{prompt.version}
                </Badge>
                {hasChanges && (
                  <Badge variant="outline" className="text-xs text-amber-600 border-amber-500/30 bg-amber-500/10">
                    Unsaved changes
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <Button onClick={handleSave} disabled={saving || (!hasChanges && !notes)}>
            {saving ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
                Saving...
              </>
            ) : (
              <>
                <Save className="h-4 w-4 mr-2" />
                Save New Version
              </>
            )}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="pt-6">
        <Tabs defaultValue="editor">
          <TabsList className="mb-4">
            <TabsTrigger value="editor">
              <Settings className="h-4 w-4 mr-2" />
              Editor
            </TabsTrigger>
            <TabsTrigger value="history">
              <History className="h-4 w-4 mr-2" />
              Version History
            </TabsTrigger>
          </TabsList>

          <TabsContent value="editor" className="space-y-6">
            {error && (
              <div className="rounded-lg border border-destructive bg-destructive/10 p-3">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}

            {/* System Prompt */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="system-prompt">System Prompt</Label>
                <span className="text-xs text-muted-foreground">
                  {systemPrompt.length.toLocaleString()} characters
                </span>
              </div>
              <Textarea
                id="system-prompt"
                value={systemPrompt}
                onChange={(e) => handlePromptChange(e.target.value)}
                className="min-h-[400px] font-mono text-sm"
                placeholder="Enter the system prompt for this agent..."
              />
            </div>

            {/* Parameters */}
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="temperature">Temperature</Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="temperature"
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={temperature}
                    onChange={(e) => handleTemperatureChange(parseFloat(e.target.value) || 0)}
                    className="w-24"
                  />
                  <span className="text-xs text-muted-foreground">
                    0 = deterministic, 2 = creative
                  </span>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="max-tokens">Max Tokens</Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="max-tokens"
                    type="number"
                    min={100}
                    max={16000}
                    step={100}
                    value={maxTokens}
                    onChange={(e) => handleMaxTokensChange(parseInt(e.target.value) || 1000)}
                    className="w-24"
                  />
                  <span className="text-xs text-muted-foreground">
                    Maximum response length
                  </span>
                </div>
              </div>
            </div>

            {/* Version Notes */}
            <div className="space-y-2">
              <Label htmlFor="notes">Version Notes (optional)</Label>
              <Input
                id="notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Describe what changed in this version..."
              />
              <p className="text-xs text-muted-foreground">
                Add a note to help identify this version later
              </p>
            </div>
          </TabsContent>

          <TabsContent value="history">
            <VersionHistory
              dimension={dimension}
              currentVersion={prompt.version}
              onRollback={handleRollback}
            />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
