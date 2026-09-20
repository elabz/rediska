"""Message sync service.

Syncs conversations and messages from providers (e.g., Reddit) to the local database.
"""

import asyncio
import json
import logging
import re
import httpx
from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from pathlib import Path

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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

# Scheduled syncs stop after this many listing pages (100 messages each) even
# without an early exit, so a run that cannot recognise already-stored messages
# costs a bounded number of Reddit requests. Full walks belong to the backfills.
PERIODIC_SYNC_MAX_PAGES = 5
# The on-demand "Sync now" gets more room to catch up after downtime.
MANUAL_SYNC_MAX_PAGES = 20
# On-demand syncs and backfills wait this long for a running sync to finish.
ON_DEMAND_LOCK_WAIT_SECONDS = 60

SYNC_LOCK_KEY = "rediska:lock:message_sync:reddit:{identity_id}"
# Outlives the Celery hard time limit (600s) so a killed task's lock expires on
# its own; long backfills renew it after every page.
SYNC_LOCK_TIMEOUT_SECONDS = 660


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
        # Listing pages requested from the provider during the run
        self.pages_fetched = 0
        # Another sync for the same identity held the lock, so nothing ran
        self.skipped = False
        # A database failure stopped the run; pages committed before it are kept
        self.aborted = False


class MessageSyncService:
    """Service for syncing messages from providers."""

    # Markdown image syntax pattern: [text](url)
    MARKDOWN_IMAGE_PATTERN = r'\[([^\]]*)\]\((https?://[^\)]+)\)'

    # Image URL patterns to detect in message bodies
    IMAGE_URL_PATTERNS = [
        # Reddit hosted images
        r'https?://i\.redd\.it/[^\s\)]+',
        r'https?://preview\.redd\.it/[^\s\)]+',
        # Reddit Matrix media (new format used in private messages)
        # e.g., https://matrix.redditspace.com/_matrix/media/v3/download/reddit.com/abc123
        r'https?://matrix\.redditspace\.com/_matrix/media/[^\s\)]+',
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

    def __init__(self, db: Session, redis_client: Any = None):
        self.db = db
        self.settings = get_settings()
        crypto = CryptoService(self.settings.encryption_key)
        self.credentials_service = CredentialsService(db=db, crypto=crypto)
        # Injectable for tests; created lazily from settings otherwise
        self._redis = redis_client

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

        Downloads images in parallel (up to 5 concurrent) for better performance.

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

        # Download all images in parallel (max 5 concurrent to avoid overwhelming network)
        semaphore = asyncio.Semaphore(5)

        async def download_with_limit(url: str) -> tuple[str, tuple[bytes, str] | None]:
            async with semaphore:
                result = await self._download_image(url)
                return url, result

        # Download all images concurrently
        download_tasks = [download_with_limit(url) for url in image_urls]
        download_results = await asyncio.gather(*download_tasks, return_exceptions=True)

        # Store successful downloads
        count = 0
        for dl_result in download_results:
            if isinstance(dl_result, BaseException):
                logger.error(f"Error downloading image for message {message_id}: {dl_result}")
                continue

            url, download_data = dl_result
            if download_data is None:
                logger.warning(f"Failed to download image from {url}")
                continue

            try:
                data, content_type = download_data

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
        thread_external_id: Optional[str] = None,
        parent_external_message_id: Optional[str] = None,
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

        # For outgoing messages, check if there's a pending or sent-without-id local message
        # that matches (created before sync got the external_id from Reddit)
        if direction == "out":
            from sqlalchemy import or_
            # Look for outgoing messages in the same conversation that lack an external_message_id.
            # Two cases:
            # 1. remote_visibility == "unknown" — pending send (not yet confirmed)
            # 2. remote_visibility == "visible" AND external_message_id is NULL/empty
            #    — confirmed sent but Reddit didn't return an ID
            pending_message = (
                self.db.query(Message)
                .filter(
                    Message.provider_id == "reddit",
                    Message.conversation_id == conversation.id,
                    Message.direction == "out",
                    or_(
                        Message.remote_visibility == "unknown",  # Pending send
                        # Sent but missing external ID (Reddit often returns empty string)
                        Message.remote_visibility == "visible",
                    ),
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
            thread_external_id=thread_external_id,
            parent_external_message_id=parent_external_message_id,
        )
        self.db.add(message)
        self.db.flush()

        # Search index (and, once embedded, semantic search). Queued, so a
        # broker or ES problem never costs us the synced message.
        from rediska_core.domain.services.indexing import IndexingService

        IndexingService.enqueue_index("message", message.id)

        # Update engagement_state when receiving a new incoming message
        # from a contacted account
        if direction == "in":
            account = (
                self.db.query(ExternalAccount)
                .filter(ExternalAccount.id == conversation.counterpart_account_id)
                .first()
            )
            if (
                account
                and account.contact_state == "contacted"
                and account.engagement_state == "not_engaged"
            ):
                account.engagement_state = "engaged"
                account.first_inbound_after_contact_at = sent_at
                self.db.flush()

        # Update conversation last_activity_at
        # Compare as naive datetimes since MySQL DATETIME columns don't store timezone
        sent_at_naive = sent_at.replace(tzinfo=None) if sent_at.tzinfo else sent_at
        last_activity = conversation.last_activity_at
        if last_activity is not None and last_activity.tzinfo:
            last_activity = last_activity.replace(tzinfo=None)
        if last_activity is None or sent_at_naive > last_activity:
            conversation.last_activity_at = sent_at_naive
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

    def _acquire_sync_lock(self, identity_id: int, wait_seconds: float) -> tuple[bool, Any]:
        """Take the per-identity message sync lock.

        Returns ``(acquired, lock)``. When Redis is unreachable the sync runs
        unlocked (``lock`` is None): per-message savepoints still absorb a
        concurrent insert, so this costs efficiency rather than correctness.
        """
        try:
            if self._redis is None:
                import redis as redis_lib

                self._redis = redis_lib.Redis.from_url(self.settings.redis_url, socket_timeout=5)
            lock = self._redis.lock(
                SYNC_LOCK_KEY.format(identity_id=identity_id),
                timeout=SYNC_LOCK_TIMEOUT_SECONDS,
            )
            if wait_seconds > 0:
                acquired = lock.acquire(blocking=True, blocking_timeout=wait_seconds)
            else:
                acquired = lock.acquire(blocking=False)
        except Exception as e:
            logger.warning(f"Message sync lock unavailable, syncing unlocked: {e}")
            return True, None
        return bool(acquired), lock

    @staticmethod
    def _renew_sync_lock(lock: Any) -> None:
        """Push the lock's expiry out again so a long backfill keeps holding it."""
        if lock is None:
            return
        try:
            lock.reacquire()
        except Exception as e:
            logger.warning(f"Failed to renew message sync lock: {e}")

    @staticmethod
    def _release_sync_lock(lock: Any) -> None:
        if lock is None:
            return
        try:
            lock.release()
        except Exception as e:
            logger.warning(f"Failed to release message sync lock: {e}")

    async def sync_reddit_messages(
        self,
        identity_id: Optional[int] = None,
        inbox_only: bool = False,
        endpoints: Optional[Sequence[str]] = None,
        max_pages: Optional[int] = None,
        lock_wait_seconds: float = 0,
    ) -> MessageSyncResult:
        """Sync messages from Reddit for an identity.

        Uses early-exit optimization: stops pagination when encountering
        consecutive existing messages (since Reddit returns newest first).

        Only one sync per identity runs at a time; a run that cannot get the
        lock returns with ``skipped`` set. Each page is committed on its own and
        each message is written in a savepoint, so a duplicate insert from a
        concurrent writer affects only that message. Any other database failure
        stops the run (``aborted``) instead of paging on with a broken session.

        Args:
            identity_id: Specific identity to sync, or None for default active identity.
            inbox_only: If True, only sync inbox (not sent). Faster for catching new messages.
            endpoints: Listing endpoints to walk; overrides ``inbox_only`` when given.
            max_pages: Stop each endpoint after this many pages. None walks to the end.
            lock_wait_seconds: How long to wait for a sync that is already running.
                0 skips immediately.

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

        acquired, lock = self._acquire_sync_lock(identity.id, lock_wait_seconds)
        if not acquired:
            logger.info(f"Message sync for identity {identity.id} is already running; skipping")
            result.skipped = True
            return result

        adapter: Optional[RedditAdapter] = None
        try:
            try:
                adapter = self._get_reddit_adapter(identity)
            except SyncError as e:
                result.errors.append(str(e))
                return result

            if endpoints is None:
                endpoints = ["/message/inbox"] if inbox_only else ["/message/inbox", "/message/sent"]

            my_username = identity.external_username.lower()
            conversation_cache: dict[str, Conversation] = {}
            processed_message_ids: set[str] = set()

            for endpoint in endpoints:
                keep_going = await self._sync_endpoint(
                    adapter=adapter,
                    endpoint=endpoint,
                    identity=identity,
                    my_username=my_username,
                    conversation_cache=conversation_cache,
                    processed_message_ids=processed_message_ids,
                    result=result,
                    max_pages=max_pages,
                    lock=lock,
                )
                if not keep_going:
                    break

            return result
        finally:
            if adapter is not None:
                await adapter.aclose()
            self._release_sync_lock(lock)

    async def _sync_endpoint(
        self,
        adapter: RedditAdapter,
        endpoint: str,
        identity: Identity,
        my_username: str,
        conversation_cache: dict[str, Conversation],
        processed_message_ids: set[str],
        result: MessageSyncResult,
        max_pages: Optional[int],
        lock: Any,
    ) -> bool:
        """Walk one listing endpoint newest-first. Returns False if the run must stop."""
        # Early exit threshold: stop after this many consecutive existing messages
        EARLY_EXIT_THRESHOLD = 10

        cursor = None
        pages_fetched = 0
        endpoint_messages = 0
        consecutive_existing = 0
        logger.info(f"Starting to fetch messages from {endpoint}")

        while True:
            if max_pages is not None and pages_fetched >= max_pages:
                logger.info(
                    f"{endpoint}: Stopped at page cap of {max_pages} "
                    f"({endpoint_messages} messages processed)"
                )
                return True

            try:
                messages_page = await adapter.fetch_inbox_messages(
                    cursor=cursor, limit=100, endpoint=endpoint
                )
            except Exception as e:
                logger.error(f"Failed to fetch messages from {endpoint}: {e}")
                result.errors.append(f"Failed to fetch messages from {endpoint}: {e}")
                return True
            pages_fetched += 1
            result.pages_fetched += 1

            if not messages_page.items:
                return True

            early_exit = False
            for msg_data in messages_page.items:
                msg_id = msg_data.get("id", "")

                # Skip if missing data or already processed
                if not msg_data.get("author") or not msg_data.get("dest") or not msg_id:
                    continue
                if msg_id in processed_message_ids:
                    continue
                processed_message_ids.add(msg_id)

                try:
                    is_new = await self._ingest_reddit_message(
                        msg_data, identity, my_username, conversation_cache, result
                    )
                except SQLAlchemyError as e:
                    # Not a duplicate insert (those are absorbed per message): the
                    # database failed, e.g. a deadlock, which on MySQL discards the
                    # whole transaction. Paging on would fail every later message
                    # the same way without ever reaching the early exit, so stop.
                    self.db.rollback()
                    logger.error(f"{endpoint}: database error on message {msg_id}, stopping sync: {e}")
                    result.errors.append(f"Database error on message {msg_id}: {e}")
                    result.aborted = True
                    return False
                except Exception as e:
                    logger.warning(f"{endpoint}: failed to process message {msg_id}: {e}")
                    result.errors.append(f"Failed to process message {msg_id}: {e}")
                    continue

                if is_new is None:
                    continue
                result.messages_synced += 1
                endpoint_messages += 1

                if is_new:
                    consecutive_existing = 0
                    continue

                # Reddit returns newest first, so a run of already-stored messages
                # means everything older was synced before
                consecutive_existing += 1
                if consecutive_existing >= EARLY_EXIT_THRESHOLD:
                    logger.info(
                        f"{endpoint}: Early exit after {EARLY_EXIT_THRESHOLD} consecutive "
                        f"existing messages (page {pages_fetched}, {endpoint_messages} processed)"
                    )
                    early_exit = True
                    break

            try:
                self.db.commit()
            except SQLAlchemyError as e:
                self.db.rollback()
                logger.error(f"{endpoint}: commit failed on page {pages_fetched}, stopping sync: {e}")
                result.errors.append(f"Commit failed on {endpoint} page {pages_fetched}: {e}")
                result.aborted = True
                return False
            self._renew_sync_lock(lock)

            if early_exit:
                return True

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
                return True

    async def _ingest_reddit_message(
        self,
        msg_data: dict,
        identity: Identity,
        my_username: str,
        conversation_cache: dict[str, Conversation],
        result: MessageSyncResult,
    ) -> Optional[bool]:
        """Store one raw Reddit message.

        Returns True if it was new, False if it was already stored, and None if
        it is not part of a conversation (a message to or from ourselves).
        """
        author = msg_data["author"]
        msg_id = msg_data["id"]
        first_message_name = msg_data.get("first_message_name") or msg_data.get("name", "")

        # Determine counterpart (the other person)
        if author.lower() == my_username:
            counterpart_username = msg_data["dest"]
            direction = "out"
        else:
            counterpart_username = author
            direction = "in"

        # Skip messages to/from ourselves (edge case)
        if counterpart_username.lower() == my_username:
            return None

        # Create canonical conversation ID
        # For [deleted] users, use thread ID to keep conversations separate
        if counterpart_username.lower() == "[deleted]" and first_message_name:
            conv_id = f"reddit:thread:{first_message_name}"
        else:
            # Normal users: group by user pair
            user_pair = tuple(sorted([my_username, counterpart_username.lower()]))
            conv_id = f"reddit:pair:{user_pair[0]}:{user_pair[1]}"

        body_text = msg_data.get("body", "")
        sent_at = self._parse_reddit_timestamp(msg_data.get("created_utc"))

        conversation: Optional[Conversation] = None
        message: Optional[Message] = None
        is_new_conv = False
        is_new_msg = False
        for attempt in (1, 2):
            try:
                with self.db.begin_nested():
                    conversation = conversation_cache.get(conv_id)
                    is_new_conv = False
                    if conversation is None:
                        counterpart_account = self._get_or_create_external_account(
                            username=counterpart_username,
                            user_id=None,
                        )
                        conversation, is_new_conv = self._get_or_create_conversation(
                            identity=identity,
                            external_conversation_id=conv_id,
                            counterpart_account=counterpart_account,
                        )
                    message, is_new_msg = self._create_message_if_not_exists(
                        conversation=conversation,
                        identity=identity,
                        external_message_id=msg_id,
                        direction=direction,
                        body_text=body_text,
                        sent_at=sent_at,
                        sender_username=author,
                        thread_external_id=first_message_name or "",
                        parent_external_message_id=msg_data.get("parent_id", ""),
                    )
                break
            except IntegrityError:
                # Another writer (e.g. the send worker) inserted this account,
                # conversation or message between our lookup and our insert. The
                # savepoint discarded only this message's writes; retrying lets
                # the lookups find the row that now exists.
                conversation_cache.pop(conv_id, None)
                if attempt == 2:
                    raise
                logger.info(f"Message {msg_id} was written concurrently; retrying its lookup")

        if conversation is not None and conv_id not in conversation_cache:
            conversation_cache[conv_id] = conversation
            result.conversations_synced += 1
            if is_new_conv:
                result.new_conversations += 1

        if is_new_msg:
            result.new_messages += 1
            if message is not None:
                await self._store_message_images(
                    message, msg_data, body_text, counterpart_username, result
                )

        return is_new_msg

    async def _store_message_images(
        self,
        message: Message,
        msg_data: dict,
        body_text: str,
        username: str,
        result: MessageSyncResult,
    ) -> None:
        """Download images referenced by a newly stored message (best effort)."""
        msg_id = msg_data["id"]
        try:
            # Extract media attachments from Reddit message metadata
            media_attachments = self._extract_media_attachments_from_reddit(msg_data)

            # Extract image URLs from message body text
            image_urls = self._extract_image_urls(body_text)

            # Combine both sources, deduplicated while preserving order
            all_urls = list(dict.fromkeys(media_attachments + image_urls))

            if not all_urls:
                logger.debug(f"No images found in message {msg_id}")
                return

            logger.debug(
                f"Found {len(all_urls)} media attachments in message {msg_id}: "
                f"{len(media_attachments)} from metadata, {len(image_urls)} from body text"
            )
            # Savepoint: a failed attachment insert must not break the rest of the page
            with self.db.begin_nested():
                images_saved = await self._download_and_store_images(
                    message_id=message.id,
                    image_urls=all_urls,
                    username=username,
                )
            logger.info(f"Message {msg_id}: extracted {len(all_urls)} URLs, saved {images_saved} images")
        except Exception as img_err:
            logger.error(f"Failed to download images for message {msg_id}: {img_err}", exc_info=True)
            result.errors.append(f"Failed to download images for message {msg_id}: {img_err}")

    async def sync_inbox_only(
        self,
        identity_id: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> MessageSyncResult:
        """Fast sync of inbox only - for catching new incoming messages quickly.

        This is a lightweight sync that only checks the inbox (not sent folder),
        making it suitable for frequent polling (e.g., every 60 seconds).

        Args:
            identity_id: Specific identity to sync, or None for default active identity.
            max_pages: Stop after this many pages. None walks to the end.

        Returns:
            MessageSyncResult with counts of synced items.
        """
        return await self.sync_reddit_messages(
            identity_id=identity_id, endpoints=["/message/inbox"], max_pages=max_pages
        )

    async def sync_sent_only(
        self,
        identity_id: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> MessageSyncResult:
        """Sync the sent folder only.

        The sent folder changes only when a message is sent from another Reddit
        client (sends from Rediska are stored locally first), so this can poll
        far less often than the inbox.

        Args:
            identity_id: Specific identity to sync, or None for default active identity.
            max_pages: Stop after this many pages. None walks to the end.

        Returns:
            MessageSyncResult with counts of synced items.
        """
        return await self.sync_reddit_messages(
            identity_id=identity_id, endpoints=["/message/sent"], max_pages=max_pages
        )

    def _parse_reddit_timestamp(self, ts: float | None) -> datetime:
        """Parse a Reddit UTC timestamp."""
        if ts is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
