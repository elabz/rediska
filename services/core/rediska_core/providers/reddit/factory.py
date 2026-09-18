"""Build a Reddit adapter for a stored identity.

Shared by core routes that call the provider on the user's behalf (source
discovery location lookups). Token refreshes are written back to the
encrypted credential store.
"""

import json
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.config import get_settings
from rediska_core.domain.models import Identity
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.reddit.adapter import RedditAdapter


class AdapterUnavailableError(Exception):
    """No usable identity or credentials to call Reddit with."""


def adapter_for_identity(db: Session, identity_id: Optional[int] = None) -> RedditAdapter:
    """Reddit adapter for ``identity_id``, or the default active Reddit identity.

    Raises:
        AdapterUnavailableError: when there is no active identity, no
            encryption key, or no stored OAuth tokens.
    """
    settings = get_settings()

    query = db.query(Identity).filter(
        Identity.provider_id == "reddit", Identity.is_active.is_(True)
    )
    if identity_id:
        identity = query.filter(Identity.id == identity_id).first()
    else:
        identity = (
            query.filter(Identity.is_default.is_(True)).first() or query.first()
        )
    if not identity:
        raise AdapterUnavailableError("No active Reddit identity found")

    if not settings.encryption_key:
        raise AdapterUnavailableError("Encryption key not configured")

    credentials = CredentialsService(db=db, crypto=CryptoService(settings.encryption_key))
    secret = credentials.get_credential_decrypted(
        provider_id="reddit",
        identity_id=identity.id,
        credential_type="oauth_tokens",
    )
    if not secret:
        raise AdapterUnavailableError("No Reddit credentials found for the identity")

    tokens = json.loads(secret)

    def on_token_refresh(new_access_token: str) -> None:
        tokens["access_token"] = new_access_token
        credentials.store_credential(
            provider_id="reddit",
            identity_id=identity.id,
            credential_type="oauth_tokens",
            secret=json.dumps(tokens),
        )

    return RedditAdapter(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        client_id=settings.provider_reddit_client_id or "",
        client_secret=settings.provider_reddit_client_secret or "",
        user_agent=settings.provider_reddit_user_agent,
        on_token_refresh=on_token_refresh,
    )
