"""Reddit provider integration.

This package contains:
- OAuth flow handling
- API adapter
- Data mappers
"""

from rediska_core.providers.reddit.adapter import (
    MAX_PROFILE_COMMENTS,
    MAX_PROFILE_POSTS,
    RedditAdapter,
    RedditAPIError,
)
from rediska_core.providers.reddit.oauth import OAuthError, RedditOAuthService

__all__ = [
    "MAX_PROFILE_COMMENTS",
    "MAX_PROFILE_POSTS",
    "OAuthError",
    "RedditAdapter",
    "RedditAPIError",
    "RedditOAuthService",
]
