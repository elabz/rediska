export function getInitials(username: string): string {
  return username.slice(0, 2).toUpperCase();
}

export function normalizeUtc(s: string): string {
  return s.endsWith('Z') || s.includes('+') ? s : s + 'Z';
}

export function formatMessageTime(dateString: string): string {
  const date = new Date(normalizeUtc(dateString));
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  }

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `Yesterday ${date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`;
  }

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
