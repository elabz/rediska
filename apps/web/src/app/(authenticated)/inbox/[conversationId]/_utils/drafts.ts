export interface DraftValue {
  text: string;
  attachmentIds: number[];
}

export function draftKey(conversationId: string): string {
  return `rediska:draft:conversation:${conversationId}`;
}

export function readDraft(conversationId: string): DraftValue {
  if (typeof window === 'undefined') return { text: '', attachmentIds: [] };
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(draftKey(conversationId));
  } catch (err) {
    console.warn('Failed to read message draft from localStorage', err);
    try {
      window.localStorage.removeItem(draftKey(conversationId));
    } catch {
      // ignore secondary failure
    }
    return { text: '', attachmentIds: [] };
  }
  if (raw === null) return { text: '', attachmentIds: [] };

  // Legacy values were plain strings; structured values are JSON objects with a
  // `text: string` field. Anything else (parse failure, non-object, missing
  // `text`) is treated as legacy text so we don't silently drop a typed draft.
  try {
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === 'object' &&
      !Array.isArray(parsed) &&
      typeof (parsed as { text?: unknown }).text === 'string'
    ) {
      const candidate = parsed as { text: string; attachmentIds?: unknown };
      const attachmentIds = Array.isArray(candidate.attachmentIds)
        ? candidate.attachmentIds.filter((v): v is number => typeof v === 'number')
        : [];
      return { text: candidate.text, attachmentIds };
    }
  } catch {
    // fall through to legacy handling
  }
  return { text: raw, attachmentIds: [] };
}

export function writeDraft(conversationId: string, value: DraftValue): void {
  if (typeof window === 'undefined') return;
  try {
    if (value.text.trim() === '' && value.attachmentIds.length === 0) {
      window.localStorage.removeItem(draftKey(conversationId));
    } else {
      window.localStorage.setItem(draftKey(conversationId), JSON.stringify(value));
    }
  } catch (err) {
    console.warn('Failed to write message draft to localStorage', err);
  }
}

export function clearDraft(conversationId: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(draftKey(conversationId));
  } catch (err) {
    console.warn('Failed to clear message draft from localStorage', err);
  }
}
