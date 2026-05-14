/**
 * Translates Reddit API error codes into human-readable explanations.
 */
export function getSendErrorExplanation(error: string | null): string {
  if (!error) return 'Message could not be delivered.';

  const errorLower = error.toLowerCase();

  if (errorLower.includes('not_whitelisted_by_user_message') || errorLower.includes("can't send a message to that user")) {
    return 'This user has their privacy settings configured to only accept messages from whitelisted users. You are not on their whitelist.';
  }
  if (errorLower.includes('user_blocked')) {
    return 'This user has blocked you. You cannot send messages to them.';
  }
  if (errorLower.includes('user_muted')) {
    return 'This user has muted you. They will not receive your messages.';
  }
  if (errorLower.includes('no_user') || errorLower.includes('user_doesnt_exist')) {
    return 'This user account no longer exists or has been deleted.';
  }
  if (errorLower.includes('user_is_suspended')) {
    return 'This user\'s account has been suspended by Reddit.';
  }
  if (errorLower.includes('ratelimit') || errorLower.includes('rate_limit')) {
    return 'Reddit rate limit reached. Please wait a few minutes and try resending.';
  }
  if (errorLower.includes('invalid_permission')) {
    return 'Your Reddit account does not have permission to send messages. This may be due to low karma or a new account.';
  }
  if (errorLower.includes('no credential') || errorLower.includes('no_credential')) {
    return 'No Reddit credentials found for this identity. Please re-authenticate in Settings.';
  }
  if (errorLower.includes('thread_locked')) {
    return 'This conversation thread has been locked and no longer accepts new messages.';
  }
  if (errorLower.includes('gold_required')) {
    return 'This action requires Reddit Premium (Gold).';
  }

  return error;
}
