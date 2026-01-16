"""Message sync service.

Syncs conversations and messages from providers (e.g., Reddit) to the local database.
"""

import json
import logging
import re
import httpx
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from sqlalchemy.orm import Session

from rediska_core.config import get_settings
from rediska_core.domain.models import (
    Attachment,
    Conversation,
    ExternalAccount,
    Identity,
    Message,
)
from rediska_core.domain.services.credentials import CredentialsService
from rediska_core.infrastructure.crypto import CryptoService
from rediska_core.providers.reddit.adapter import RedditAdapter

logger = logging.getLogger(__name__)


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

    # Markdown image syntax pattern: [text](url)
    MARKDOWN_IMAGE_PATTERN = r'\[([^\]]*)\]\((https?://[^\)]+)\)'

    # Image URL patterns to detect in message bodies
    IMAGE_URL_PATTERNS = [
        # Reddit hosted images
        r'https?://i\.redd\.it/[^\s\)]+',
        r'https?://preview\.redd\.it/[^\s\)]+',
        # Imgur
        r'https?://(?:i\.)?imgur\.com/[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)',
        # Generic image URLs
        r'https?://[^\s\)]+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s\)]*)?',
    ]

    # Allowed image content types
    ALLOWED_IMAGE_TYPES = {
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
    }

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        crypto = CryptoService(self.settings.encryption_key)
        self.credentials_service = CredentialsService(db=db, crypto=crypto)

    def _extract_media_attachments_from_reddit(self, msg_data: dict) -> list[str]:
        """Extract attachment URLs from Reddit private message data.

        Handles:
        - media_metadata: Images/videos in messages
        - media.oembed: Embedded content
        """
        attachments = []

        # Check for media_metadata (images/videos in messages)
        if "media_metadata" in msg_data and msg_data["media_metadata"]:
            for media_id, media_info in msg_data["media_metadata"].items():
                if media_info.get("type") == "giphy.gif":
                    # Giphy GIF
                    if "url" in media_info.get("s", {}):
                        attachments.append(media_info["s"]["url"])
                elif media_info.get("type") in ("reddit_video", "giphy.gif"):
                    # Video or GIF - try to get thumbnail
                    if "p" in media_info:
                        # Get highest res thumbnail
                        for size in reversed(media_info["p"]):
                            if "x" in size:
                                attachments.append(size["x"])
                                break
                else:
                    # Image - get original
                    if "s" in media_info and "x" in media_info["s"]:
                        attachments.append(media_info["s"]["x"])

        # Check for embeds (inline videos, etc)
        if "media" in msg_data and msg_data["media"]:
            media = msg_data["media"]
            if "oembed" in media:
                oembed = media["oembed"]
                if oembed.get("type") == "rich":
                    if "thumbnail_url" in oembed:
                        attachments.append(oembed["thumbnail_url"])

        return attachments[:5]  # Limit to 5 attachments per message

    def _extract_image_urls(self, text: str) -> list[str]:
        """
        Extract image URLs from message text.

        Supports:
        - Bare URLs: https://i.redd.it/abc.jpg
        - Markdown syntax: [alt text](https://example.com/image.jpg)
        """
        if not text:
            return []

        urls = []

        # Extract markdown image URLs: [text](url)
        markdown_matches = re.findall(self.MARKDOWN_IMAGE_PATTERN, text)
        for alt_text, url in markdown_matches:
            urls.append(url)

        # Extract bare URLs (existing patterns)
        for pattern in self.IMAGE_URL_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            urls.extend(matches)

        # Deduplicate while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            # Normalize URL (remove trailing punctuation that might have been captured)
            url = url.rstrip('.,;:!?)')
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        return unique_urls[:5]  # Limit to 5 images per message

    async def _download_image(self, url: str) -> tuple[bytes, str] | None:
        """Download an image from URL. Returns (data, content_type) or None on failure."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={'User-Agent': self.settings.provider_reddit_user_agent}
                )

                if response.status_code != 200:
                    return None

                content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
                if content_type not in self.ALLOWED_IMAGE_TYPES:
                    return None

                # Limit to 10MB
                content = response.content
                if len(content) > 10 * 1024 * 1024:
                    return None

                return content, content_type

        except Exception:
            return None

    async def _download_and_store_images(
        self,
        message_id: int,
        image_urls: list[str],
        username: Optional[str] = None,
    ) -> int:
        """Download images and create attachments. Returns count of images saved.

        Args:
            message_id: ID of the message to link attachments to.
            image_urls: List of image URLs to download.
            username: Optional username to organize files by (counterpart username).
        """
        if not image_urls:
            return 0

        from rediska_core.domain.services.attachment import AttachmentService

        attachment_service = AttachmentService(
            db=self.db,
            storage_path=self.settings.attachments_path,
        )

        count = 0
        for url in image_urls:
            try:
                result = await self._download_image(url)
                if result is None:
                    logger.warning(f"Failed to download image from {url}")
                    continue

                data, content_type = result

                # Generate a filename from URL
                url_path = url.split('?')[0].split('/')[-1]
                if '.' not in url_path:
                    ext = content_type.split('/')[-1]
                    url_path = f"image.{ext}"

                upload_result = attachment_service.upload(
                    file_data=data,
                    filename=url_path,
                    content_type=content_type,
                    message_id=message_id,
                    username=username,
                )
                count += 1
                logger.debug(f"Stored image attachment {upload_result.attachment_id} for message {message_id}")
            except Exception as e:
                logger.error(f"Error storing image from {url} for message {message_id}: {e}")
                continue

        if count > 0:
            logger.info(f"Downloaded and stored {count} images for message {message_id}")
        return count

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
        """Create a message if it doesn't exist. Returns (message, is_new).

        For outgoing messages, also checks for pending messages that were created
        locally but haven't been synced yet (to avoid duplicates when sync runs
        before the send worker completes).
        """
        # Check if message already exists by external_message_id
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

        # For outgoing messages, check if there's a pending local message
        # that matches (created before sync got the external_id from Reddit)
        if direction == "out":
            # Look for a pending outgoing message in the same conversation
            # with matching body text (normalized) that was sent recently
            from sqlalchemy import or_
            pending_message = (
                self.db.query(Message)
                .filter(
                    Message.provider_id == "reddit",
                    Message.conversation_id == conversation.id,
                    Message.direction == "out",
                    Message.remote_visibility == "unknown",  # Pending send
                    # Not yet synced (NULL or empty string)
                    or_(
                        Message.external_message_id.is_(None),
                        Message.external_message_id == "",
                    ),
                    Message.deleted_at.is_(None),  # Not deleted
                )
                .order_by(Message.sent_at.desc())
                .first()
            )

            if pending_message:
                # Normalize body text for comparison (strip whitespace)
                pending_body = (pending_message.body_text or "").strip()
                sync_body = (body_text or "").strip()

                # Check if body text matches (exact match after stripping)
                if pending_body == sync_body:
                    # Found matching pending message - update it instead of creating duplicate
                    logger.info(
                        f"Found pending message {pending_message.id} matching synced message {external_message_id}, "
                        f"updating instead of creating duplicate"
                    )
                    pending_message.external_message_id = external_message_id
                    pending_message.remote_visibility = "visible"
                    # Use Reddit's timestamp for consistency across Reddit apps
                    pending_message.sent_at = sent_at
                    self.db.flush()
                    return pending_message, False  # Not a new message

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

    async def backfill_attachments_for_existing_messages(
        self,
        identity_id: Optional[int] = None,
        limit: int = 100,
    ) -> dict:
        """Backfill attachments for existing messages that may have been synced before extraction was added.

        Args:
            identity_id: Specific identity, or None for default
            limit: Maximum new attachments to create

        Returns:
            Dict with results: {"messages_processed": int, "attachments_created": int, "errors": []}
        """
        result = {
            "messages_processed": 0,
            "attachments_created": 0,
            "errors": [],
        }

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
                identity = (
                    self.db.query(Identity)
                    .filter_by(provider_id="reddit", is_active=True)
                    .first()
                )

        if not identity:
            return result

        try:
            adapter = self._get_reddit_adapter(identity)
        except SyncError as e:
            result["errors"].append(str(e))
            return result

        my_username = identity.external_username.lower()
        my_attachment_count = 0

        # Fetch raw messages again to get latest metadata
        endpoints = ["/message/inbox", "/message/sent"]

        for endpoint in endpoints:
            cursor = None
            pages_fetched = 0

            while my_attachment_count < limit:
                try:
                    messages_page = await adapter.fetch_inbox_messages(
                        cursor=cursor, limit=100, endpoint=endpoint
                    )
                    pages_fetched += 1

                    if not messages_page.items:
                        break

                    for msg_data in messages_page.items:
                        if my_attachment_count >= limit:
                            break

                        try:
                            msg_id = msg_data.get("id", "")
                            if not msg_id:
                                continue

                            # Find existing message in DB
                            message = (
                                self.db.query(Message)
                                .filter(Message.provider_id == "reddit", Message.external_message_id == msg_id)
                                .first()
                            )

                            if not message:
                                continue

                            # Check if already has attachments
                            if len(message.attachments) > 0:
                                continue

                            # Extract media attachments
                            media_attachments = self._extract_media_attachments_from_reddit(msg_data)

                            # Extract image URLs from body
                            image_urls = self._extract_image_urls(message.body_text or "")

                            # Combine
                            all_urls = media_attachments + image_urls
                            all_urls = list(dict.fromkeys(all_urls))

                            # Download - get username for storage organization
                            counterpart_username = None
                            if message.conversation and message.conversation.counterpart_account:
                                counterpart_username = message.conversation.counterpart_account.external_username

                            if all_urls:
                                logger.debug(f"Backfilling attachments for message {msg_id}: {len(all_urls)} URLs")
                                images_saved = await self._download_and_store_images(
                                    message_id=message.id,
                                    image_urls=all_urls,
                                    username=counterpart_username,
                                )
                                if images_saved > 0:
                                    my_attachment_count += images_saved
                                    result["attachments_created"] += images_saved
                                    logger.info(f"Message {msg_id}: backfilled {images_saved} attachments")

                            result["messages_processed"] += 1

                        except Exception as e:
                            logger.error(f"Error backfilling message {msg_data.get('id')}: {e}")
                            result["errors"].append(str(e))

                    # Log progress every 10 pages
                    if pages_fetched % 10 == 0:
                        logger.info(
                            f"Attachment backfill {endpoint}: Page {pages_fetched}, "
                            f"{result['messages_processed']} messages checked, "
                            f"{result['attachments_created']} attachments created"
                        )

                    cursor = messages_page.next_cursor
                    if not messages_page.has_more or not cursor:
                        logger.info(
                            f"Attachment backfill {endpoint}: Completed after {pages_fetched} pages"
                        )
                        break

                except Exception as e:
                    result["errors"].append(f"Failed to fetch messages from {endpoint}: {e}")
                    break

        return result

    async def redownload_missing_attachments(
        self,
        conversation_id: Optional[int] = None,
        limit: int = 100,
    ) -> dict:
        """Re-download missing attachments from message body text.

        This method scans messages for image URLs and attempts to download
        any images that are not already stored as attachments. Unlike
        backfill_attachments_for_existing_messages, this does NOT call the
        Reddit API - it only extracts URLs from the locally stored body_text.

        Args:
            conversation_id: Specific conversation, or None for all
            limit: Maximum new attachments to create

        Returns:
            Dict with results: {
                "messages_scanned": int,
                "urls_found": int,
                "attachments_created": int,
                "already_exists": int,
                "download_failed": int,
                "errors": []
            }
        """
        from rediska_core.domain.services.attachment import AttachmentService

        result = {
            "messages_scanned": 0,
            "urls_found": 0,
            "attachments_created": 0,
            "already_exists": 0,
            "download_failed": 0,
            "errors": [],
        }

        attachment_service = AttachmentService(
            db=self.db,
            storage_path=self.settings.attachments_path,
        )

        # Build query for messages
        query = self.db.query(Message).filter(
            Message.body_text.isnot(None),
            Message.body_text != "",
        )

        if conversation_id:
            query = query.filter(Message.conversation_id == conversation_id)

        # Order by most recent first
        query = query.order_by(Message.sent_at.desc())

        # Fetch messages in batches
        batch_size = 100
        offset = 0
        attachments_created = 0

        while attachments_created < limit:
            messages = query.offset(offset).limit(batch_size).all()
            if not messages:
                break

            for message in messages:
                if attachments_created >= limit:
                    break

                result["messages_scanned"] += 1

                # Extract image URLs from body text
                image_urls = self._extract_image_urls(message.body_text or "")
                if not image_urls:
                    continue

                result["urls_found"] += len(image_urls)

                # Get counterpart username for storage organization
                counterpart_username = None
                if message.conversation and message.conversation.counterpart_account:
                    counterpart_username = message.conversation.counterpart_account.external_username

                # Get existing attachment SHA256s for this message
                existing_sha256s = set()
                for att in message.attachments:
                    if att.sha256:
                        existing_sha256s.add(att.sha256)

                # Download and store images
                for url in image_urls:
                    if attachments_created >= limit:
                        break

                    try:
                        download_result = await self._download_image(url)
                        if download_result is None:
                            logger.warning(f"Failed to download image from {url}")
                            result["download_failed"] += 1
                            continue

                        data, content_type = download_result

                        # Check if we already have this image (by SHA256)
                        import hashlib
                        sha256_hash = hashlib.sha256(data).hexdigest()

                        if sha256_hash in existing_sha256s:
                            result["already_exists"] += 1
                            continue

                        # Also check if any attachment with this SHA256 exists for this message
                        existing_att = (
                            self.db.query(Attachment)
                            .filter(
                                Attachment.message_id == message.id,
                                Attachment.sha256 == sha256_hash,
                            )
                            .first()
                        )
                        if existing_att:
                            existing_sha256s.add(sha256_hash)
                            result["already_exists"] += 1
                            continue

                        # Generate filename from URL
                        url_path = url.split('?')[0].split('/')[-1]
                        if '.' not in url_path:
                            ext = content_type.split('/')[-1]
                            url_path = f"image.{ext}"

                        upload_result = attachment_service.upload(
                            file_data=data,
                            filename=url_path,
                            content_type=content_type,
                            message_id=message.id,
                            username=counterpart_username,
                        )

                        existing_sha256s.add(sha256_hash)
                        attachments_created += 1
                        result["attachments_created"] += 1
                        logger.debug(
                            f"Re-downloaded attachment {upload_result.attachment_id} "
                            f"for message {message.id}"
                        )

                    except Exception as e:
                        logger.error(f"Error downloading/storing image from {url}: {e}")
                        result["errors"].append(f"URL {url}: {str(e)}")
                        result["download_failed"] += 1

            offset += batch_size

            # Commit periodically
            self.db.commit()

            logger.info(
                f"Redownload progress: scanned {result['messages_scanned']} messages, "
                f"created {result['attachments_created']} attachments"
            )

        return result

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

        for endpoint in endpoints:
            cursor = None
            pages_fetched = 0
            endpoint_messages = 0
            logger.info(f"Starting to fetch messages from {endpoint}")

            while True:  # Continue until Reddit returns no more data
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
                        body_text = msg_data.get("body", "")
                        message, is_new_msg = self._create_message_if_not_exists(
                            conversation=conversation,
                            identity=identity,
                            external_message_id=msg_id,
                            direction=direction,
                            body_text=body_text,
                            sent_at=sent_at,
                            sender_username=author,
                        )

                        if is_new_msg:
                            result.new_messages += 1

                            # Download images for new messages
                            if message:
                                try:
                                    # Extract media attachments from Reddit message metadata
                                    media_attachments = self._extract_media_attachments_from_reddit(msg_data)

                                    # Extract image URLs from message body text
                                    image_urls = self._extract_image_urls(body_text)

                                    # Combine both sources
                                    all_urls = media_attachments + image_urls
                                    all_urls = list(dict.fromkeys(all_urls))  # Deduplicate while preserving order

                                    if all_urls:
                                        logger.debug(f"Found {len(all_urls)} media attachments in message {msg_id}: {len(media_attachments)} from metadata, {len(image_urls)} from body text")
                                        images_saved = await self._download_and_store_images(
                                            message_id=message.id,
                                            image_urls=all_urls,
                                            username=counterpart_username,
                                        )
                                        logger.info(f"Message {msg_id}: extracted {len(all_urls)} URLs, saved {images_saved} images")
                                    else:
                                        logger.debug(f"No images found in message {msg_id}")
                                except Exception as img_err:
                                    logger.error(f"Failed to download images for message {msg_id}: {img_err}", exc_info=True)
                                    result.errors.append(f"Failed to download images for message {msg_id}: {img_err}")

                        result.messages_synced += 1
                        endpoint_messages += 1

                    except Exception as e:
                        result.errors.append(f"Failed to process message: {e}")

                # Log progress every 10 pages
                if pages_fetched % 10 == 0:
                    logger.info(
                        f"{endpoint}: Page {pages_fetched}, "
                        f"{endpoint_messages} messages processed, "
                        f"{result.new_messages} new"
                    )

                # Move to next page
                cursor = messages_page.next_cursor
                if not messages_page.has_more or not cursor:
                    logger.info(
                        f"{endpoint}: Completed after {pages_fetched} pages, "
                        f"{endpoint_messages} messages total"
                    )
                    break

        # Commit all changes
        self.db.commit()

        return result

    def _parse_reddit_timestamp(self, ts: float | None) -> datetime:
        """Parse a Reddit UTC timestamp."""
        if ts is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
