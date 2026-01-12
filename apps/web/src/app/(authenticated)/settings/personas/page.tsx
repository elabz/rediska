'use client';

import { useState, useEffect, useCallback } from 'react';
import { Plus, Pencil, Trash2, Loader2, User, Sparkles, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface VoiceConfig {
  tone?: string;
  style?: string;
  persona_name?: string;
  system_prompt?: string;
}

interface Persona {
  id: number;
  display_name: string;
  is_active: boolean;
  voice_config_json: VoiceConfig | null;
  created_at: string;
}

interface PersonaForm {
  display_name: string;
  voice_config_json: VoiceConfig;
}

const defaultForm: PersonaForm = {
  display_name: '',
  voice_config_json: {
    tone: '',
    style: '',
    persona_name: '',
    system_prompt: '',
  },
};

export default function PersonasPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingPersona, setEditingPersona] = useState<Persona | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [form, setForm] = useState<PersonaForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const fetchPersonas = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/core/identities', {
        credentials: 'include',
      });
      if (response.ok) {
        const data = await response.json();
        const identities = data.identities || [];
        setPersonas(identities);
      }
    } catch {
      // Silent fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPersonas();
  }, [fetchPersonas]);

  const handleCreate = () => {
    setIsCreating(true);
    setEditingPersona(null);
    setForm({
      display_name: '',
      voice_config_json: {
        tone: 'professional',
        style: 'concise',
        persona_name: '',
        system_prompt: '',
      },
    });
    setError('');
  };

  const handleEdit = (persona: Persona) => {
    setEditingPersona(persona);
    setIsCreating(false);
    setForm({
      display_name: persona.display_name,
      voice_config_json: persona.voice_config_json || {},
    });
    setError('');
  };

  const handleClose = () => {
    setEditingPersona(null);
    setIsCreating(false);
    setError('');
  };

  const handleSave = async () => {
    if (!form.display_name.trim()) {
      setError('Persona name is required');
      return;
    }

    setSaving(true);
    setError('');

    try {
      if (isCreating) {
        // For creating, we need to use the existing identity creation endpoint
        // This would need backend support - for now show a message
        setError('Creating new personas requires connecting Reddit first. Edit an existing persona instead.');
        setSaving(false);
        return;
      }

      // Update existing persona
      const response = await fetch(`/api/core/identities/${editingPersona!.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          display_name: form.display_name,
          voice_config_json: form.voice_config_json,
        }),
      });

      if (response.ok) {
        const updated = await response.json();
        setPersonas((prev) =>
          prev.map((p) => (p.id === updated.id ? updated : p))
        );
        handleClose();
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to save persona');
      }
    } catch {
      setError('Network error. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const handleSetDefault = async (persona: Persona) => {
    // Set this persona as active (default)
    try {
      // First, deactivate all others
      for (const p of personas) {
        if (p.id !== persona.id && p.is_active) {
          await fetch(`/api/core/identities/${p.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ is_active: false }),
          });
        }
      }
      // Activate this one
      const response = await fetch(`/api/core/identities/${persona.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ is_active: true }),
      });
      if (response.ok) {
        fetchPersonas();
      }
    } catch {
      // Silent fail
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div className="flex justify-between items-center">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-9 w-32" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Voice Personas</h1>
          <p className="text-muted-foreground text-sm">
            Create different voices for different situations
          </p>
        </div>
        {personas.length > 0 && (
          <Button onClick={handleCreate} disabled>
            <Plus className="mr-2 h-4 w-4" />
            New Persona
          </Button>
        )}
      </div>

      {/* Personas Grid */}
      {personas.length === 0 ? (
        <Card className="text-center py-12">
          <CardContent>
            <Sparkles className="mx-auto h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium mb-2">No personas yet</h3>
            <p className="text-muted-foreground mb-4">
              Connect your Reddit account first, then you can customize your voice persona.
            </p>
            <Button asChild>
              <a href="/settings/connection">Connect Reddit</a>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {personas.map((persona) => (
            <Card
              key={persona.id}
              className={`relative overflow-hidden transition-all duration-200 hover:shadow-md ${
                persona.is_active ? 'ring-2 ring-primary' : ''
              }`}
            >
              {persona.is_active && (
                <div className="absolute top-3 right-3">
                  <Badge variant="default">
                    <Check className="mr-1 h-3 w-3" />
                    Default
                  </Badge>
                </div>
              )}
              <CardHeader className="pb-2">
                <CardTitle className="text-lg flex items-center gap-2">
                  <User className="h-5 w-5 text-muted-foreground" />
                  {persona.display_name}
                </CardTitle>
                <CardDescription>
                  {persona.voice_config_json?.persona_name || 'No persona name set'}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  {persona.voice_config_json?.tone && (
                    <Badge variant="secondary" className="text-xs">
                      {persona.voice_config_json.tone}
                    </Badge>
                  )}
                  {persona.voice_config_json?.style && (
                    <Badge variant="secondary" className="text-xs">
                      {persona.voice_config_json.style}
                    </Badge>
                  )}
                </div>
                {persona.voice_config_json?.system_prompt && (
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {persona.voice_config_json.system_prompt}
                  </p>
                )}
                <div className="flex gap-2 pt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleEdit(persona)}
                  >
                    <Pencil className="mr-2 h-3 w-3" />
                    Edit
                  </Button>
                  {!persona.is_active && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleSetDefault(persona)}
                    >
                      Set as Default
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Info Card */}
      <Card className="bg-muted/30">
        <CardContent className="pt-6">
          <h3 className="font-medium mb-2">About Voice Personas</h3>
          <ul className="text-sm text-muted-foreground space-y-1">
            <li>• Personas define how AI-generated messages sound</li>
            <li>• The <strong>default</strong> persona is used automatically</li>
            <li>• Recipients always see your Reddit username, regardless of persona</li>
          </ul>
        </CardContent>
      </Card>

      {/* Edit/Create Dialog */}
      <Dialog open={!!editingPersona || isCreating} onOpenChange={handleClose}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {isCreating ? 'Create Persona' : 'Edit Persona'}
            </DialogTitle>
            <DialogDescription>
              Configure how your AI-generated messages will sound
            </DialogDescription>
          </DialogHeader>

          {error && (
            <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="displayName">Persona Name</Label>
              <Input
                id="displayName"
                value={form.display_name}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, display_name: e.target.value }))
                }
                placeholder="e.g., Professional, Casual, Sales"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="tone">Tone</Label>
                <Select
                  value={form.voice_config_json.tone || ''}
                  onValueChange={(value) =>
                    setForm((prev) => ({
                      ...prev,
                      voice_config_json: {
                        ...prev.voice_config_json,
                        tone: value,
                      },
                    }))
                  }
                >
                  <SelectTrigger id="tone">
                    <SelectValue placeholder="Select tone..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="professional">Professional</SelectItem>
                    <SelectItem value="casual">Casual</SelectItem>
                    <SelectItem value="friendly">Friendly</SelectItem>
                    <SelectItem value="formal">Formal</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="style">Style</Label>
                <Select
                  value={form.voice_config_json.style || ''}
                  onValueChange={(value) =>
                    setForm((prev) => ({
                      ...prev,
                      voice_config_json: {
                        ...prev.voice_config_json,
                        style: value,
                      },
                    }))
                  }
                >
                  <SelectTrigger id="style">
                    <SelectValue placeholder="Select style..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="concise">Concise</SelectItem>
                    <SelectItem value="detailed">Detailed</SelectItem>
                    <SelectItem value="conversational">Conversational</SelectItem>
                    <SelectItem value="technical">Technical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="personaName">Character Name (optional)</Label>
              <Input
                id="personaName"
                value={form.voice_config_json.persona_name || ''}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    voice_config_json: {
                      ...prev.voice_config_json,
                      persona_name: e.target.value,
                    },
                  }))
                }
                placeholder="e.g., Alex, Jordan"
              />
              <p className="text-xs text-muted-foreground">
                A name the AI can use when referring to itself
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="systemPrompt">Custom Instructions</Label>
              <Textarea
                id="systemPrompt"
                value={form.voice_config_json.system_prompt || ''}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    voice_config_json: {
                      ...prev.voice_config_json,
                      system_prompt: e.target.value,
                    },
                  }))
                }
                placeholder="Add specific instructions for how this persona should communicate..."
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={handleClose}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                'Save Persona'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
