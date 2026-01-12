"""Message sync service.

Syncs conversations and messages from providers (e.g., Reddit) to the local database.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from rediska_core.config import get_settings
from rediska_core.domain.models import (
    Conversation,
    ExternalAccount,
    Identity,
    Message,
)
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.reddit.adapter import RedditAdapter


class SyncError(Exception):
    """Raised when sync fails."""

    pass


class MessageSyncResult:
    """Result of a message sync operation."""

    def __init__(
        self,
        conversations_synced: int = 0,
        messages_synced: int = 0,
        new_conversations: int = 0,
        new_messages: int = 0,
        errors: list[str] | None = None,
    ):
        self.conversations_synced = conversations_synced
        self.messages_synced = messages_synced
        self.new_conversations = new_conversations
        self.new_messages = new_messages
        self.errors = errors or []


class MessageSyncService:
    """Service for syncing messages from providers."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        crypto = CryptoService(self.settings.encryption_key)
        self.credentials_service = CredentialsService(db=db, crypto=crypto)

    def _get_reddit_adapter(self, identity: Identity) -> RedditAdapter:
        """Create a Reddit adapter for the given identity."""
        # Get stored tokens
        credential = self.credentials_service.get_credential_decrypted(
            provider_id="reddit",
            identity_id=identity.id,
            credential_type="oauth_tokens",
        )

        if not credential:
            raise SyncError(f"No credentials found for identity {identity.id}")

        tokens = json.loads(credential)

        # Create callback to update tokens on refresh
        def on_token_refresh(new_access_token: str) -> None:
            tokens["access_token"] = new_access_token
            self.credentials_service.store_credential(
                provider_id="reddit",
                identity_id=identity.id,
                credential_type="oauth_tokens",
                secret=json.dumps(tokens),
            )

        return RedditAdapter(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            client_id=self.settings.provider_reddit_client_id,
            client_secret=self.settings.provider_reddit_client_secret,
            user_agent=self.settings.provider_reddit_user_agent,
            on_token_refresh=on_token_refresh,
        )

    def _get_or_create_external_account(
        self,
        username: str,
        user_id: Optional[str] = None,
    ) -> ExternalAccount:
        """Get or create an external account for a Reddit user."""
        account = (
            self.db.query(ExternalAccount)
            .filter_by(provider_id="reddit", external_username=username)
            .first()
        )

        if account:
            # Update user_id if we have it now
            if user_id and not account.external_user_id:
                account.external_user_id = user_id
                self.db.flush()
            return account

        account = ExternalAccount(
            provider_id="reddit",
            external_username=username,
            external_user_id=user_id,
            remote_status="active",
        )
        self.db.add(account)
        self.db.flush()
        return account

    def _get_or_create_conversation(
        self,
        identity: Identity,
        external_conversation_id: str,
        counterpart_account: ExternalAccount,
    ) -> tuple[Conversation, bool]:
        """Get or create a conversation. Returns (conversation, is_new)."""
        conversation = (
            self.db.query(Conversation)
            .filter_by(
                provider_id="reddit",
                external_conversation_id=external_conversation_id,
            )
            .first()
        )

        if conversation:
            return conversation, False

        conversation = Conversation(
            provider_id="reddit",
            external_conversation_id=external_conversation_id,
            counterpart_account_id=counterpart_account.id,
            identity_id=identity.id,
        )
        self.db.add(conversation)
        self.db.flush()
        return conversation, True

    def _create_message_if_not_exists(
        self,
        conversation: Conversation,
        identity: Identity,
        external_message_id: str,
        direction: str,
        body_text: str,
        sent_at: datetime,
        sender_username: Optional[str] = None,
    ) -> tuple[Message | None, bool]:
        """Create a message if it doesn't exist. Returns (message, is_new)."""
        # Check if message already exists
        existing = (
            self.db.query(Message)
            .filter_by(
                provider_id="reddit",
                external_message_id=external_message_id,
            )
            .first()
        )

        if existing:
            return existing, False

        # Determine direction based on sender
        if direction == "in":
            identity_id = None  # Incoming messages don't have our identity
        else:
            identity_id = identity.id

        message = Message(
            provider_id="reddit",
            external_message_id=external_message_id,
            conversation_id=conversation.id,
            identity_id=identity_id,
            direction=direction,
            sent_at=sent_at,
            body_text=body_text,
            remote_visibility="visible",
        )
        self.db.add(message)
        self.db.flush()

        # Update conversation last_activity_at
        if conversation.last_activity_at is None or sent_at > conversation.last_activity_at:
            conversation.last_activity_at = sent_at
            self.db.flush()

        return message, True

    async def sync_reddit_messages(
        self,
        identity_id: Optional[int] = None,
    ) -> MessageSyncResult:
        """Sync messages from Reddit for an identity.

        Args:
            identity_id: Specific identity to sync, or None for default active identity.

        Returns:
            MessageSyncResult with counts of synced items.
        """
        result = MessageSyncResult()

        # Get identity
        if identity_id:
            identity = (
                self.db.query(Identity)
                .filter_by(id=identity_id, is_active=True)
                .first()
            )
        else:
            identity = (
                self.db.query(Identity)
                .filter_by(provider_id="reddit", is_active=True, is_default=True)
                .first()
            )
            if not identity:
                # Fall back to any active Reddit identity
                identity = (
                    self.db.query(Identity)
                    .filter_by(provider_id="reddit", is_active=True)
                    .first()
                )

        if not identity:
            raise SyncError("No active Reddit identity found")

        try:
            adapter = self._get_reddit_adapter(identity)
        except SyncError as e:
            result.errors.append(str(e))
            return result

        my_username = identity.external_username.lower()

        # Fetch ALL messages from both inbox AND sent folders
        # This ensures we get complete conversation histories
        conversation_cache: dict[str, tuple] = {}  # conv_id -> (Conversation, counterpart)
        processed_message_ids: set[str] = set()

        # Fetch from both endpoints
        endpoints = ["/message/inbox", "/message/sent"]
        max_pages_per_endpoint = 50  # Safety limit to prevent infinite loops

        for endpoint in endpoints:
            cursor = None
            pages_fetched = 0
            while pages_fetched < max_pages_per_endpoint:
                try:
                    # Fetch a page of raw messages
                    messages_page = await adapter.fetch_inbox_messages(
                        cursor=cursor, limit=100, endpoint=endpoint
                    )
                    pages_fetched += 1
                except Exception as e:
                    result.errors.append(f"Failed to fetch messages from {endpoint}: {e}")
                    break

                if not messages_page.items:
                    break

                for msg_data in messages_page.items:
                    try:
                        author = msg_data.get("author", "")
                        dest = msg_data.get("dest", "")
                        msg_id = msg_data.get("id", "")
                        first_message_name = msg_data.get("first_message_name") or msg_data.get("name", "")

                        # Skip if missing data or already processed
                        if not author or not dest or not msg_id:
                            continue
                        if msg_id in processed_message_ids:
                            continue
                        processed_message_ids.add(msg_id)

                        # Determine counterpart (the other person)
                        if author.lower() == my_username:
                            counterpart_username = dest
                            direction = "out"
                        else:
                            counterpart_username = author
                            direction = "in"

                        # Skip messages to/from ourselves (edge case)
                        if counterpart_username.lower() == my_username:
                            continue

                        # Create canonical conversation ID
                        # For [deleted] users, use thread ID to keep conversations separate
                        if counterpart_username.lower() == "[deleted]" and first_message_name:
                            # Use thread ID for deleted users to keep them separate
                            conv_id = f"reddit:thread:{first_message_name}"
                        else:
                            # Normal users: group by user pair
                            user_pair = tuple(sorted([my_username, counterpart_username.lower()]))
                            conv_id = f"reddit:pair:{user_pair[0]}:{user_pair[1]}"

                        # Get or create conversation (cached)
                        if conv_id not in conversation_cache:
                            counterpart_account = self._get_or_create_external_account(
                                username=counterpart_username,
                                user_id=None,
                            )
                            conversation, is_new_conv = self._get_or_create_conversation(
                                identity=identity,
                                external_conversation_id=conv_id,
                                counterpart_account=counterpart_account,
                            )
                            conversation_cache[conv_id] = (conversation, counterpart_username)
                            if is_new_conv:
                                result.new_conversations += 1
                            result.conversations_synced += 1
                        else:
                            conversation, _ = conversation_cache[conv_id]

                        # Create message
                        sent_at = self._parse_reddit_timestamp(msg_data.get("created_utc"))
                        _, is_new_msg = self._create_message_if_not_exists(
                            conversation=conversation,
                            identity=identity,
                            external_message_id=msg_id,
                            direction=direction,
                            body_text=msg_data.get("body", ""),
                            sent_at=sent_at,
                            sender_username=author,
                        )

                        if is_new_msg:
                            result.new_messages += 1
                        result.messages_synced += 1

                    except Exception as e:
                        result.errors.append(f"Failed to process message: {e}")

                # Move to next page
                cursor = messages_page.next_cursor
                if not messages_page.has_more or not cursor:
                    break

        # Commit all changes
        self.db.commit()

        return result

    def _parse_reddit_timestamp(self, ts: float | None) -> datetime:
        """Parse a Reddit UTC timestamp."""
        if ts is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
