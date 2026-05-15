/**
 * Phrase-based search helpers.
 *
 * The conversation page treats the query as a single literal phrase (case-
 * insensitive), to match the backend `match_phrase` behavior on the global
 * search side. Surrounding double quotes are stripped so `"hello world"` and
 * `hello world` behave identically. Phrases shorter than 2 chars are ignored
 * to avoid highlighting every "a" / "I" in a conversation.
 */

export function extractPhrase(query: string | null | undefined): string | null {
  if (!query) return null;
  let q = query.trim();
  if (q.length === 0) return null;
  if (q.length >= 2 && q.startsWith('"') && q.endsWith('"')) {
    q = q.slice(1, -1).trim();
  }
  if (q.length < 2) return null;
  return q;
}

export function buildPhrasePattern(phrase: string | null): RegExp | null {
  if (!phrase) return null;
  const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`(${escape(phrase)})`, 'gi');
}
