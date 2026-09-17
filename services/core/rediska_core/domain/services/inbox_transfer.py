"""Inbox export / import / clear services.

Implements the `inbox-export`, `inbox-import`, and `inbox-clear` capabilities.

Scope of "inbox" (see openspec/changes/inbox-export-restore/design.md):
    conversations, conversation list memberships, messages, and message-linked
    attachments.

Identities and external accounts are *included in the dump* so that an import
can rebuild foreign keys, but they are never deleted by a clear -- lead posts,
profile snapshots, and profile items reference the same accounts.

Attachment file *content* is never embedded; the dump carries storage keys and
metadata only. Clear deletes attachment rows but leaves files on disk, so a
later import restores working references.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from rediska_core.domain.models import (
    Attachment,
    AuditLog,
    Conversation,
    ConversationList,
    ConversationListMember,
    ExternalAccount,
    Identity,
    Message,
    ProfileItem,
)

logger = logging.getLogger(__name__)

DUMP_FORMAT = "rediska.inbox"
DUMP_VERSION = 1

# Rows pulled from the DB per batch when serializing/restoring.
BATCH_SIZE = 500

ProgressCallback = Callable[[str, int, int], None]
"""Called as (stage, done, total) during long-running operations."""


def _noop_progress(stage: str, done: int, total: int) -> None:
    return None


def _iso(value: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to ISO-8601, or None."""
    if value is None:
        return None
    return value.isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string back to a naive UTC datetime.

    The schema stores naive DATETIME columns, so any tz-aware input is
    converted to UTC and stripped, keeping round-trips stable.
    """
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _body_fingerprint(
    conversation_key: str, sent_at: Optional[datetime], direction: str, body: Optional[str]
) -> str:
    """Stable identity for a message that has no external message ID.

    Unsent drafts and locally-composed messages have `external_message_id` NULL,
    so the natural key cannot be used for duplicate detection.
    """
    raw = f"{conversation_key}|{_iso(sent_at)}|{direction}|{body or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class InvalidDumpError(ValueError):
    """Raised when a dump file fails structural validation."""


# =============================================================================
# Export
# =============================================================================


class InboxExportService:
    """Serialize inbox content to a portable JSON dump."""

    def __init__(self, db: Session, attachments_path: str) -> None:
        self.db = db
        self.attachments_path = Path(attachments_path)

    # -- helpers ----------------------------------------------------------

    def _attachment_exists(self, storage_key: str) -> bool:
        """Check that an attachment's backing file is present on disk."""
        try:
            return (self.attachments_path / storage_key).is_file()
        except OSError:  # pragma: no cover - defensive against odd keys
            return False

    def _counts(self) -> dict[str, int]:
        return {
            "conversations": self.db.scalar(select(func.count(Conversation.id))) or 0,
            "messages": self.db.scalar(select(func.count(Message.id))) or 0,
            "attachments": self.db.scalar(
                select(func.count(Attachment.id)).where(Attachment.message_id.isnot(None))
            )
            or 0,
        }

    # -- serializers ------------------------------------------------------

    def _serialize_identities(self) -> list[dict[str, Any]]:
        rows = self.db.scalars(select(Identity)).all()
        return [
            {
                "provider_id": r.provider_id,
                "external_username": r.external_username,
                "external_user_id": r.external_user_id,
                "display_name": r.display_name,
                "voice_config_json": r.voice_config_json,
                "is_default": r.is_default,
                "is_active": r.is_active,
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]

    def _serialize_accounts(self) -> list[dict[str, Any]]:
        rows = self.db.scalars(select(ExternalAccount)).all()
        return [
            {
                "provider_id": r.provider_id,
                "external_username": r.external_username,
                "external_user_id": r.external_user_id,
                "remote_status": r.remote_status,
                "remote_status_last_seen_at": _iso(r.remote_status_last_seen_at),
                "analysis_state": r.analysis_state,
                "contact_state": r.contact_state,
                "engagement_state": r.engagement_state,
                "first_analyzed_at": _iso(r.first_analyzed_at),
                "first_contacted_at": _iso(r.first_contacted_at),
                "first_inbound_after_contact_at": _iso(r.first_inbound_after_contact_at),
                "is_starred": r.is_starred,
                "starred_at": _iso(r.starred_at),
                "deleted_at": _iso(r.deleted_at),
                "purged_at": _iso(r.purged_at),
                "last_fetched_at": _iso(r.last_fetched_at),
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]

    def _serialize_conversations(
        self, progress: ProgressCallback, total: int
    ) -> tuple[list[dict[str, Any]], dict[int, str]]:
        """Return conversation dicts plus an id -> natural-key map for messages."""
        out: list[dict[str, Any]] = []
        key_by_id: dict[int, str] = {}
        done = 0

        stmt = (
            select(Conversation, ExternalAccount, Identity)
            .join(ExternalAccount, Conversation.counterpart_account_id == ExternalAccount.id)
            .join(Identity, Conversation.identity_id == Identity.id)
            .order_by(Conversation.id)
            .execution_options(yield_per=BATCH_SIZE)
        )

        for conv, account, identity in self.db.execute(stmt):
            key_by_id[conv.id] = f"{conv.provider_id}:{conv.external_conversation_id}"
            out.append(
                {
                    "provider_id": conv.provider_id,
                    "external_conversation_id": conv.external_conversation_id,
                    "counterpart_username": account.external_username,
                    "identity_username": identity.external_username,
                    "created_at": _iso(conv.created_at),
                    "updated_at": _iso(conv.updated_at),
                    "last_activity_at": _iso(conv.last_activity_at),
                    "archived_at": _iso(conv.archived_at),
                    "deleted_at": _iso(conv.deleted_at),
                }
            )
            done += 1
            if done % BATCH_SIZE == 0:
                progress("conversations", done, total)

        progress("conversations", done, total)
        return out, key_by_id

    def _serialize_lists(self, key_by_id: dict[int, str]) -> tuple[list, list]:
        lists = self.db.scalars(select(ConversationList)).all()
        list_rows = [
            {
                "name": r.name,
                "created_at": _iso(r.created_at),
                "updated_at": _iso(r.updated_at),
            }
            for r in lists
        ]

        name_by_id = {r.id: r.name for r in lists}
        members = self.db.scalars(select(ConversationListMember)).all()
        member_rows = [
            {
                "list_name": name_by_id[m.list_id],
                "conversation_key": key_by_id[m.conversation_id],
                "added_at": _iso(m.added_at),
            }
            for m in members
            if m.list_id in name_by_id and m.conversation_id in key_by_id
        ]
        return list_rows, member_rows

    def _serialize_messages(
        self, key_by_id: dict[int, str], progress: ProgressCallback, total: int
    ) -> tuple[list[dict[str, Any]], dict[int, str]]:
        """Return message dicts plus an id -> dump-key map for attachments."""
        out: list[dict[str, Any]] = []
        key_by_msg_id: dict[int, str] = {}
        done = 0

        stmt = (
            select(Message, Identity.external_username)
            .outerjoin(Identity, Message.identity_id == Identity.id)
            .order_by(Message.id)
            .execution_options(yield_per=BATCH_SIZE)
        )

        for msg, identity_username in self.db.execute(stmt):
            conversation_key = key_by_id.get(msg.conversation_id)
            if conversation_key is None:
                # Orphaned message; its conversation was not exported.
                continue

            dump_key = msg.external_message_id or _body_fingerprint(
                conversation_key, msg.sent_at, msg.direction, msg.body_text
            )
            key_by_msg_id[msg.id] = dump_key

            out.append(
                {
                    "dump_key": dump_key,
                    "provider_id": msg.provider_id,
                    "external_message_id": msg.external_message_id,
                    "conversation_key": conversation_key,
                    "identity_username": identity_username,
                    "direction": msg.direction,
                    "sent_at": _iso(msg.sent_at),
                    "body_text": msg.body_text,
                    "remote_visibility": msg.remote_visibility,
                    "remote_deleted_at": _iso(msg.remote_deleted_at),
                    "send_error": msg.send_error,
                    "thread_external_id": msg.thread_external_id,
                    "parent_external_message_id": msg.parent_external_message_id,
                    "deleted_at": _iso(msg.deleted_at),
                    "created_at": _iso(msg.created_at),
                }
            )
            done += 1
            if done % BATCH_SIZE == 0:
                progress("messages", done, total)

        progress("messages", done, total)
        return out, key_by_msg_id

    def _serialize_attachments(
        self, key_by_msg_id: dict[int, str], progress: ProgressCallback, total: int
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Return attachment dicts plus the storage keys whose files are missing."""
        out: list[dict[str, Any]] = []
        missing: list[str] = []
        done = 0

        stmt = (
            select(Attachment)
            .where(Attachment.message_id.isnot(None))
            .order_by(Attachment.id)
            .execution_options(yield_per=BATCH_SIZE)
        )

        for att in self.db.scalars(stmt):
            if att.message_id is None:
                continue
            message_key = key_by_msg_id.get(att.message_id)
            if message_key is None:
                continue

            file_present = self._attachment_exists(att.storage_key)
            if not file_present:
                missing.append(att.storage_key)

            out.append(
                {
                    "message_key": message_key,
                    "storage_backend": att.storage_backend,
                    "storage_key": att.storage_key,
                    "sha256": att.sha256,
                    "mime_type": att.mime_type,
                    "size_bytes": att.size_bytes,
                    "width_px": att.width_px,
                    "height_px": att.height_px,
                    "remote_visibility": att.remote_visibility,
                    "remote_deleted_at": _iso(att.remote_deleted_at),
                    "deleted_at": _iso(att.deleted_at),
                    "created_at": _iso(att.created_at),
                    "file_present": file_present,
                }
            )
            done += 1
            if done % BATCH_SIZE == 0:
                progress("attachments", done, total)

        progress("attachments", done, total)
        return out, missing

    # -- public API -------------------------------------------------------

    def build_dump(self, progress: ProgressCallback = _noop_progress) -> dict[str, Any]:
        """Build the full in-memory dump structure."""
        counts = self._counts()

        conversations, conv_key_by_id = self._serialize_conversations(
            progress, counts["conversations"]
        )
        lists, list_members = self._serialize_lists(conv_key_by_id)
        messages, msg_key_by_id = self._serialize_messages(
            conv_key_by_id, progress, counts["messages"]
        )
        attachments, missing_files = self._serialize_attachments(
            msg_key_by_id, progress, counts["attachments"]
        )

        identities = self._serialize_identities()
        accounts = self._serialize_accounts()

        return {
            "format": DUMP_FORMAT,
            "version": DUMP_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "identities": len(identities),
                "external_accounts": len(accounts),
                "conversations": len(conversations),
                "conversation_lists": len(lists),
                "conversation_list_members": len(list_members),
                "messages": len(messages),
                "attachments": len(attachments),
            },
            "identities": identities,
            "external_accounts": accounts,
            "conversations": conversations,
            "conversation_lists": lists,
            "conversation_list_members": list_members,
            "messages": messages,
            "attachments": attachments,
            "warnings": {"missing_files": missing_files},
        }

    def write_dump(
        self, output_path: str | Path, progress: ProgressCallback = _noop_progress
    ) -> dict[str, Any]:
        """Write a dump to disk and return a summary.

        The dump is written to a temporary sibling file and moved into place, so
        a partially-written file is never visible under the final name.
        """
        dump = self.build_dump(progress)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".partial")

        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(dump, handle, ensure_ascii=False)
        temp_path.replace(output_path)

        return {
            "path": str(output_path),
            "filename": output_path.name,
            "size_bytes": output_path.stat().st_size,
            "counts": dump["counts"],
            "warnings": dump["warnings"],
        }


# =============================================================================
# Import
# =============================================================================

_REQUIRED_SECTIONS = (
    "identities",
    "external_accounts",
    "conversations",
    "messages",
    "attachments",
)


class InboxImportService:
    """Restore inbox content from a dump produced by `InboxExportService`."""

    def __init__(self, db: Session, attachments_path: str) -> None:
        self.db = db
        self.attachments_path = Path(attachments_path)

    # -- validation -------------------------------------------------------

    @staticmethod
    def validate(dump: Any) -> None:
        """Validate dump structure, raising `InvalidDumpError` on any problem."""
        if not isinstance(dump, dict):
            raise InvalidDumpError("Dump must be a JSON object")

        if dump.get("format") != DUMP_FORMAT:
            raise InvalidDumpError(
                f"Unrecognized dump format {dump.get('format')!r}; expected {DUMP_FORMAT!r}"
            )

        version = dump.get("version")
        if version != DUMP_VERSION:
            raise InvalidDumpError(
                f"Unsupported dump version {version!r}; this build reads version {DUMP_VERSION}"
            )

        for section in _REQUIRED_SECTIONS:
            if section not in dump:
                raise InvalidDumpError(f"Dump is missing required section {section!r}")
            if not isinstance(dump[section], list):
                raise InvalidDumpError(f"Dump section {section!r} must be a list")

        for conv in dump["conversations"]:
            for field in ("provider_id", "external_conversation_id", "counterpart_username"):
                if not conv.get(field):
                    raise InvalidDumpError(f"Conversation entry is missing {field!r}")

        for msg in dump["messages"]:
            for field in ("dump_key", "conversation_key", "direction", "sent_at"):
                if not msg.get(field):
                    raise InvalidDumpError(f"Message entry is missing {field!r}")

    @staticmethod
    def load(path: str | Path) -> dict[str, Any]:
        """Read and validate a dump file from disk."""
        try:
            with open(path, encoding="utf-8") as handle:
                dump = json.load(handle)
        except json.JSONDecodeError as exc:
            raise InvalidDumpError(f"File is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise InvalidDumpError(f"Could not read dump file: {exc}") from exc

        InboxImportService.validate(dump)
        return dump

    # -- restore helpers --------------------------------------------------

    def _restore_accounts(self, rows: Iterable[dict[str, Any]]) -> dict[str, int]:
        """Upsert external accounts, returning username -> id."""
        id_by_username: dict[str, int] = {}

        for row in rows:
            username = row["external_username"]
            existing = self.db.scalars(
                select(ExternalAccount).where(
                    ExternalAccount.provider_id == row["provider_id"],
                    ExternalAccount.external_username == username,
                )
            ).first()

            if existing is not None:
                id_by_username[username] = existing.id
                continue

            account = ExternalAccount(
                provider_id=row["provider_id"],
                external_username=username,
                external_user_id=row.get("external_user_id"),
                remote_status=row.get("remote_status", "unknown"),
                remote_status_last_seen_at=_parse_dt(row.get("remote_status_last_seen_at")),
                analysis_state=row.get("analysis_state", "not_analyzed"),
                contact_state=row.get("contact_state", "not_contacted"),
                engagement_state=row.get("engagement_state", "not_engaged"),
                first_analyzed_at=_parse_dt(row.get("first_analyzed_at")),
                first_contacted_at=_parse_dt(row.get("first_contacted_at")),
                first_inbound_after_contact_at=_parse_dt(
                    row.get("first_inbound_after_contact_at")
                ),
                is_starred=row.get("is_starred", False),
                starred_at=_parse_dt(row.get("starred_at")),
                deleted_at=_parse_dt(row.get("deleted_at")),
                purged_at=_parse_dt(row.get("purged_at")),
                last_fetched_at=_parse_dt(row.get("last_fetched_at")),
            )
            self.db.add(account)
            self.db.flush()
            id_by_username[username] = account.id

        return id_by_username

    def _identity_map(self) -> dict[str, int]:
        """Map identity username -> id for identities already in this instance."""
        return {
            identity.external_username: identity.id
            for identity in self.db.scalars(select(Identity)).all()
        }

    def _restore_conversations(
        self,
        rows: Iterable[dict[str, Any]],
        account_ids: dict[str, int],
        identity_ids: dict[str, int],
        progress: ProgressCallback,
        total: int,
    ) -> tuple[dict[str, int], int, int]:
        """Upsert conversations. Returns (key -> id, created, skipped)."""
        id_by_key: dict[str, int] = {}
        created = skipped = 0

        for index, row in enumerate(rows, start=1):
            key = f"{row['provider_id']}:{row['external_conversation_id']}"

            existing = self.db.scalars(
                select(Conversation).where(
                    Conversation.provider_id == row["provider_id"],
                    Conversation.external_conversation_id == row["external_conversation_id"],
                )
            ).first()
            if existing is not None:
                id_by_key[key] = existing.id
                skipped += 1
                continue

            account_id = account_ids.get(row["counterpart_username"])
            identity_id = identity_ids.get(row.get("identity_username") or "")
            if account_id is None or identity_id is None:
                # Both columns are NOT NULL; without a mapping the row cannot exist.
                raise InvalidDumpError(
                    f"Conversation {key!r} references an unknown "
                    f"counterpart or identity and cannot be restored"
                )

            conversation = Conversation(
                provider_id=row["provider_id"],
                external_conversation_id=row["external_conversation_id"],
                counterpart_account_id=account_id,
                identity_id=identity_id,
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
                last_activity_at=_parse_dt(row.get("last_activity_at")),
                archived_at=_parse_dt(row.get("archived_at")),
                deleted_at=_parse_dt(row.get("deleted_at")),
            )
            self.db.add(conversation)
            self.db.flush()
            id_by_key[key] = conversation.id
            created += 1

            if index % BATCH_SIZE == 0:
                progress("conversations", index, total)

        progress("conversations", total, total)
        return id_by_key, created, skipped

    def _restore_lists(
        self,
        list_rows: Iterable[dict[str, Any]],
        member_rows: Iterable[dict[str, Any]],
        conversation_ids: dict[str, int],
    ) -> int:
        id_by_name = {
            row.name: row.id for row in self.db.scalars(select(ConversationList)).all()
        }

        for row in list_rows:
            if row["name"] in id_by_name:
                continue
            conv_list = ConversationList(
                name=row["name"],
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                updated_at=_parse_dt(row.get("updated_at")) or datetime.utcnow(),
            )
            self.db.add(conv_list)
            self.db.flush()
            id_by_name[row["name"]] = conv_list.id

        restored = 0
        for row in member_rows:
            list_id = id_by_name.get(row["list_name"])
            conversation_id = conversation_ids.get(row["conversation_key"])
            if list_id is None or conversation_id is None:
                continue

            exists = self.db.scalars(
                select(ConversationListMember).where(
                    ConversationListMember.list_id == list_id,
                    ConversationListMember.conversation_id == conversation_id,
                )
            ).first()
            if exists is not None:
                continue

            self.db.add(
                ConversationListMember(
                    list_id=list_id,
                    conversation_id=conversation_id,
                    added_at=_parse_dt(row.get("added_at")) or datetime.utcnow(),
                )
            )
            restored += 1

        return restored

    def _existing_message_keys(self, conversation_ids: Iterable[int]) -> set[str]:
        """Build the set of dump keys already present, for duplicate detection."""
        conversation_ids = list(conversation_ids)
        if not conversation_ids:
            return set()

        key_by_conv_id = {
            conv.id: f"{conv.provider_id}:{conv.external_conversation_id}"
            for conv in self.db.scalars(
                select(Conversation).where(Conversation.id.in_(conversation_ids))
            ).all()
        }

        keys: set[str] = set()
        stmt = (
            select(Message)
            .where(Message.conversation_id.in_(conversation_ids))
            .execution_options(yield_per=BATCH_SIZE)
        )
        for msg in self.db.scalars(stmt):
            if msg.external_message_id:
                keys.add(msg.external_message_id)
            else:
                keys.add(
                    _body_fingerprint(
                        key_by_conv_id[msg.conversation_id],
                        msg.sent_at,
                        msg.direction,
                        msg.body_text,
                    )
                )
        return keys

    def _restore_messages(
        self,
        rows: list[dict[str, Any]],
        conversation_ids: dict[str, int],
        identity_ids: dict[str, int],
        progress: ProgressCallback,
    ) -> tuple[dict[str, int], int, int]:
        """Insert messages. Returns (dump_key -> id, created, skipped)."""
        total = len(rows)
        seen = self._existing_message_keys(conversation_ids.values())
        id_by_key: dict[str, int] = {}
        created = skipped = 0

        for index, row in enumerate(rows, start=1):
            conversation_id = conversation_ids.get(row["conversation_key"])
            if conversation_id is None:
                skipped += 1
                continue

            dump_key = row["dump_key"]
            if dump_key in seen:
                skipped += 1
                continue

            message = Message(
                provider_id=row["provider_id"],
                external_message_id=row.get("external_message_id"),
                conversation_id=conversation_id,
                identity_id=identity_ids.get(row.get("identity_username") or ""),
                direction=row["direction"],
                sent_at=_parse_dt(row["sent_at"]),
                body_text=row.get("body_text"),
                remote_visibility=row.get("remote_visibility", "unknown"),
                remote_deleted_at=_parse_dt(row.get("remote_deleted_at")),
                send_error=row.get("send_error"),
                thread_external_id=row.get("thread_external_id"),
                parent_external_message_id=row.get("parent_external_message_id"),
                deleted_at=_parse_dt(row.get("deleted_at")),
                created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
            )
            self.db.add(message)
            self.db.flush()

            seen.add(dump_key)
            id_by_key[dump_key] = message.id
            created += 1

            if index % BATCH_SIZE == 0:
                progress("messages", index, total)

        progress("messages", total, total)
        return id_by_key, created, skipped

    def _restore_attachments(
        self,
        rows: list[dict[str, Any]],
        message_ids: dict[str, int],
        progress: ProgressCallback,
    ) -> tuple[int, int, list[str]]:
        """Insert attachments. Returns (created, skipped, missing file keys)."""
        total = len(rows)
        created = skipped = 0
        missing: list[str] = []

        for index, row in enumerate(rows, start=1):
            message_id = message_ids.get(row["message_key"])
            if message_id is None:
                # The parent message was a duplicate or was skipped.
                skipped += 1
                continue

            exists = self.db.scalars(
                select(Attachment).where(
                    Attachment.message_id == message_id,
                    Attachment.sha256 == row["sha256"],
                )
            ).first()
            if exists is not None:
                skipped += 1
                continue

            if not (self.attachments_path / row["storage_key"]).is_file():
                missing.append(row["storage_key"])

            self.db.add(
                Attachment(
                    message_id=message_id,
                    storage_backend=row.get("storage_backend", "fs"),
                    storage_key=row["storage_key"],
                    sha256=row["sha256"],
                    mime_type=row["mime_type"],
                    size_bytes=row["size_bytes"],
                    width_px=row.get("width_px"),
                    height_px=row.get("height_px"),
                    remote_visibility=row.get("remote_visibility", "unknown"),
                    remote_deleted_at=_parse_dt(row.get("remote_deleted_at")),
                    deleted_at=_parse_dt(row.get("deleted_at")),
                    created_at=_parse_dt(row.get("created_at")) or datetime.utcnow(),
                )
            )
            created += 1

            if index % BATCH_SIZE == 0:
                progress("attachments", index, total)

        progress("attachments", total, total)
        return created, skipped, missing

    # -- public API -------------------------------------------------------

    def restore(
        self, dump: dict[str, Any], progress: ProgressCallback = _noop_progress
    ) -> dict[str, Any]:
        """Restore a dump atomically.

        Everything happens inside one transaction: on any failure the
        transaction is rolled back and the inbox is left exactly as it was.
        """
        self.validate(dump)

        try:
            account_ids = self._restore_accounts(dump["external_accounts"])
            identity_ids = self._identity_map()

            conversation_ids, conv_created, conv_skipped = self._restore_conversations(
                dump["conversations"],
                account_ids,
                identity_ids,
                progress,
                len(dump["conversations"]),
            )
            lists_restored = self._restore_lists(
                dump.get("conversation_lists", []),
                dump.get("conversation_list_members", []),
                conversation_ids,
            )
            message_ids, msg_created, msg_skipped = self._restore_messages(
                dump["messages"], conversation_ids, identity_ids, progress
            )
            att_created, att_skipped, missing_files = self._restore_attachments(
                dump["attachments"], message_ids, progress
            )

            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Inbox import failed; transaction rolled back")
            raise

        return {
            "conversations": {"created": conv_created, "skipped": conv_skipped},
            "messages": {"created": msg_created, "skipped": msg_skipped},
            "attachments": {"created": att_created, "skipped": att_skipped},
            "conversation_list_members": {"created": lists_restored},
            "warnings": {"missing_files": missing_files},
        }


# =============================================================================
# Clear
# =============================================================================


class InboxClearService:
    """Delete inbox content while preserving system configuration.

    Providers, identities, credentials, external accounts, agent prompts, leads,
    and profile data are all left untouched. Attachment *files* stay on disk so
    that a subsequent import restores working references.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def clear(
        self, confirm: bool = False, progress: ProgressCallback = _noop_progress
    ) -> dict[str, Any]:
        """Delete inbox rows. Requires `confirm=True`."""
        if not confirm:
            raise ValueError("Clear requires explicit confirmation")

        try:
            # Every message is going, so "attachments linked to a message" is
            # exactly the set in scope -- no need to materialize message ids.
            # Attachments that profile items point at must survive; detach them
            # from the message instead of deleting, so the FK does not block.
            progress("attachments", 1, 4)
            referenced = select(ProfileItem.attachment_id).where(
                ProfileItem.attachment_id.isnot(None)
            )
            detached = (
                self.db.execute(
                    update(Attachment)
                    .where(
                        Attachment.message_id.isnot(None),
                        Attachment.id.in_(referenced),
                    )
                    .values(message_id=None)
                ).rowcount
                or 0
            )
            deleted_attachments = (
                self.db.execute(
                    delete(Attachment).where(Attachment.message_id.isnot(None))
                ).rowcount
                or 0
            )

            progress("list_members", 2, 4)
            deleted_members = (
                self.db.execute(delete(ConversationListMember)).rowcount or 0
            )

            progress("messages", 3, 4)
            deleted_messages = self.db.execute(delete(Message)).rowcount or 0

            progress("conversations", 4, 4)
            deleted_conversations = self.db.execute(delete(Conversation)).rowcount or 0

            audit = AuditLog(
                ts=datetime.now(timezone.utc),
                actor="user",
                action_type="inbox.clear",
                result="ok",
                entity_type="inbox",
                request_json={"confirm": True},
                response_json={
                    "conversations": deleted_conversations,
                    "messages": deleted_messages,
                    "attachments": deleted_attachments,
                    "attachments_detached": detached,
                    "conversation_list_members": deleted_members,
                },
            )
            self.db.add(audit)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Inbox clear failed; transaction rolled back")
            raise

        return {
            "conversations": deleted_conversations,
            "messages": deleted_messages,
            "attachments": deleted_attachments,
            "attachments_detached": detached,
            "conversation_list_members": deleted_members,
        }
