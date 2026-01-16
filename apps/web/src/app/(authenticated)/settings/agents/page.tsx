'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
  AlertCircle,
  Brain,
  RefreshCw,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

import { AgentPromptList } from './components/AgentPromptList';
import { PromptEditor } from './components/PromptEditor';

// Types
export interface AgentPrompt {
  id: number;
  agent_dimension: string;
  version: number;
  system_prompt: string;
  output_schema_json: Record<string, unknown>;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  created_at: string;
  created_by: string;
  notes: string | null;
}

export interface AgentPromptsResponse {
  prompts: Record<string, AgentPrompt>;
}

export default function AgentsSettingsPage() {
  const [prompts, setPrompts] = useState<Record<string, AgentPrompt>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDimension, setSelectedDimension] = useState<string | null>(null);

  const fetchPrompts = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch('/api/core/agent-prompts', {
        credentials: 'include',
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Failed to fetch agent prompts');
      }

      const data: AgentPromptsResponse = await response.json();
      setPrompts(data.prompts);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  const handlePromptUpdated = () => {
    fetchPrompts();
    setSelectedDimension(null);
  };

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-6xl mx-auto">
        <Card className="p-8">
          <div className="text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <p className="text-destructive font-medium">{error}</p>
            <Button variant="outline" onClick={fetchPrompts} className="mt-4">
              Try Again
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
            <Brain className="h-5 w-5 text-purple-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Agent Prompts</h1>
            <p className="text-muted-foreground">
              Configure LLM agent prompts for lead analysis
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={fetchPrompts}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {/* Description Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">About Multi-Agent Analysis</CardTitle>
        </CardHeader>
        <CardContent>
          <CardDescription className="text-sm">
            The multi-agent analysis system uses 6 specialized LLM agents to analyze leads across different dimensions.
            Each agent has a configurable system prompt that defines how it interprets and analyzes profile data.
            Changes create new versions, allowing you to rollback if needed.
          </CardDescription>
        </CardContent>
      </Card>

      {/* Agent List or Editor */}
      {selectedDimension ? (
        <PromptEditor
          dimension={selectedDimension}
          prompt={prompts[selectedDimension]}
          onClose={() => setSelectedDimension(null)}
          onSaved={handlePromptUpdated}
        />
      ) : (
        <AgentPromptList
          prompts={prompts}
          onSelectAgent={setSelectedDimension}
        />
      )}
    </div>
  );
}
