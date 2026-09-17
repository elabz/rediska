"""Unit tests for inbox export / import / clear.

All fixtures below are synthetic. No real conversation content is used.
"""

from datetime import datetime, timedelta

import pytest

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
    Provider,
)
from rediska_core.domain.services.inbox_transfer import (
    DUMP_FORMAT,
    DUMP_VERSION,
    InboxClearService,
    InboxExportService,
    InboxImportService,
    InvalidDumpError,
)

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def attachments_dir(tmp_path):
    """A directory standing in for ATTACHMENTS_PATH."""
    directory = tmp_path / "attachments"
    directory.mkdir()
    return directory


@pytest.fixture
def seeded(db_session, attachments_dir):
    """Seed a small synthetic inbox and return the created objects."""
    provider = Provider(provider_id="testprov", display_name="Test Provider")
    db_session.add(provider)
    db_session.flush()

    identity = Identity(
        provider_id="testprov",
        external_username="test_identity",
        display_name="Test Identity",
        is_default=True,
    )
    account = ExternalAccount(
        provider_id="testprov",
        external_username="counterpart_one",
    )
    db_session.add_all([identity, account])
    db_session.flush()

    conversation = Conversation(
        provider_id="testprov",
        external_conversation_id="conv_1",
        counterpart_account_id=account.id,
        identity_id=identity.id,
        last_activity_at=BASE_TIME,
    )
    db_session.add(conversation)
    db_session.flush()

    # One inbound with an external id, one outbound draft without one.
    inbound = Message(
        provider_id="testprov",
        external_message_id="msg_ext_1",
        conversation_id=conversation.id,
        direction="in",
        sent_at=BASE_TIME,
        body_text="synthetic inbound body",
        remote_visibility="visible",
        thread_external_id="thread_1",
    )
    draft = Message(
        provider_id="testprov",
        external_message_id=None,
        conversation_id=conversation.id,
        identity_id=identity.id,
        direction="out",
        sent_at=BASE_TIME + timedelta(minutes=5),
        body_text="synthetic draft body",
        remote_visibility="unknown",
    )
    db_session.add_all([inbound, draft])
    db_session.flush()

    # An attachment whose file exists on disk.
    (attachments_dir / "present.png").write_bytes(b"synthetic-bytes")
    attachment = Attachment(
        message_id=inbound.id,
        storage_key="present.png",
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=15,
        width_px=1,
        height_px=1,
    )
    db_session.add(attachment)

    conv_list = ConversationList(name="Synthetic List")
    db_session.add(conv_list)
    db_session.flush()
    db_session.add(
        ConversationListMember(list_id=conv_list.id, conversation_id=conversation.id)
    )
    db_session.commit()

    return {
        "identity": identity,
        "account": account,
        "conversation": conversation,
        "inbound": inbound,
        "draft": draft,
        "attachment": attachment,
        "list": conv_list,
    }


@pytest.fixture
def export_service(db_session, attachments_dir):
    return InboxExportService(db=db_session, attachments_path=str(attachments_dir))


@pytest.fixture
def import_service(db_session, attachments_dir):
    return InboxImportService(db=db_session, attachments_path=str(attachments_dir))


@pytest.fixture
def clear_service(db_session):
    return InboxClearService(db=db_session)


# =============================================================================
# 7.1 Export
# =============================================================================


class TestExport:
    def test_dump_has_expected_envelope(self, export_service, seeded):
        dump = export_service.build_dump()

        assert dump["format"] == DUMP_FORMAT
        assert dump["version"] == DUMP_VERSION
        assert dump["exported_at"]

    def test_exports_all_entities(self, export_service, seeded):
        dump = export_service.build_dump()

        assert len(dump["conversations"]) == 1
        assert len(dump["messages"]) == 2
        assert len(dump["attachments"]) == 1
        assert len(dump["conversation_list_members"]) == 1

    def test_message_properties_are_preserved(self, export_service, seeded):
        dump = export_service.build_dump()

        inbound = next(m for m in dump["messages"] if m["external_message_id"] == "msg_ext_1")
        assert inbound["direction"] == "in"
        assert inbound["body_text"] == "synthetic inbound body"
        assert inbound["remote_visibility"] == "visible"
        assert inbound["thread_external_id"] == "thread_1"
        assert inbound["sent_at"] == BASE_TIME.isoformat()

    def test_message_without_external_id_gets_stable_dump_key(self, export_service, seeded):
        first = export_service.build_dump()
        second = export_service.build_dump()

        def draft_key(dump):
            return next(
                m["dump_key"] for m in dump["messages"] if m["external_message_id"] is None
            )

        # The fingerprint must be deterministic or duplicate detection breaks.
        assert draft_key(first) == draft_key(second)

    def test_conversation_uses_natural_keys_not_row_ids(self, export_service, seeded):
        dump = export_service.build_dump()
        conversation = dump["conversations"][0]

        assert conversation["external_conversation_id"] == "conv_1"
        assert conversation["counterpart_username"] == "counterpart_one"
        assert conversation["identity_username"] == "test_identity"
        assert "id" not in conversation

    def test_attachment_metadata_exported_without_content(self, export_service, seeded):
        dump = export_service.build_dump()
        attachment = dump["attachments"][0]

        assert attachment["storage_key"] == "present.png"
        assert attachment["mime_type"] == "image/png"
        assert attachment["size_bytes"] == 15
        assert attachment["file_present"] is True
        # File bytes must never be embedded.
        assert "content" not in attachment
        assert "data" not in attachment

    def test_missing_file_is_reported_as_warning(
        self, db_session, export_service, seeded, attachments_dir
    ):
        (attachments_dir / "present.png").unlink()

        dump = export_service.build_dump()

        assert dump["warnings"]["missing_files"] == ["present.png"]
        assert dump["attachments"][0]["file_present"] is False
        # The export still completes and still includes the attachment.
        assert len(dump["attachments"]) == 1

    def test_write_dump_creates_file_and_summary(self, export_service, seeded, tmp_path):
        target = tmp_path / "dumps" / "inbox.json"

        summary = export_service.write_dump(target)

        assert target.is_file()
        assert summary["filename"] == "inbox.json"
        assert summary["size_bytes"] > 0
        assert summary["counts"]["messages"] == 2
        # No partial file left behind.
        assert not target.with_suffix(".json.partial").exists()

    def test_export_of_empty_inbox(self, export_service):
        dump = export_service.build_dump()

        assert dump["conversations"] == []
        assert dump["messages"] == []
        assert dump["attachments"] == []

    def test_progress_callback_is_invoked(self, export_service, seeded):
        seen = []
        export_service.build_dump(progress=lambda s, d, t: seen.append(s))

        assert {"conversations", "messages", "attachments"} <= set(seen)


# =============================================================================
# 7.2 Import
# =============================================================================


class TestImportValidation:
    def test_rejects_non_object(self):
        with pytest.raises(InvalidDumpError, match="must be a JSON object"):
            InboxImportService.validate([1, 2, 3])

    def test_rejects_unknown_format(self):
        with pytest.raises(InvalidDumpError, match="Unrecognized dump format"):
            InboxImportService.validate({"format": "something-else", "version": 1})

    def test_rejects_unsupported_version(self):
        with pytest.raises(InvalidDumpError, match="Unsupported dump version"):
            InboxImportService.validate({"format": DUMP_FORMAT, "version": 99})

    def test_rejects_missing_section(self):
        with pytest.raises(InvalidDumpError, match="missing required section"):
            InboxImportService.validate({"format": DUMP_FORMAT, "version": DUMP_VERSION})

    def test_rejects_section_of_wrong_type(self):
        dump = {
            "format": DUMP_FORMAT,
            "version": DUMP_VERSION,
            "identities": [],
            "external_accounts": [],
            "conversations": {},
            "messages": [],
            "attachments": [],
        }
        with pytest.raises(InvalidDumpError, match="must be a list"):
            InboxImportService.validate(dump)

    def test_rejects_conversation_missing_field(self):
        dump = {
            "format": DUMP_FORMAT,
            "version": DUMP_VERSION,
            "identities": [],
            "external_accounts": [],
            "conversations": [{"provider_id": "testprov"}],
            "messages": [],
            "attachments": [],
        }
        with pytest.raises(InvalidDumpError, match="missing"):
            InboxImportService.validate(dump)

    def test_load_rejects_malformed_json(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")

        with pytest.raises(InvalidDumpError, match="not valid JSON"):
            InboxImportService.load(path)

    def test_load_rejects_missing_file(self, tmp_path):
        with pytest.raises(InvalidDumpError, match="Could not read"):
            InboxImportService.load(tmp_path / "nope.json")


class TestImportRestore:
    def test_round_trip_after_clear(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        assert db_session.query(Message).count() == 0

        result = import_service.restore(dump)

        assert result["conversations"]["created"] == 1
        assert result["messages"]["created"] == 2
        assert result["attachments"]["created"] == 1
        assert db_session.query(Conversation).count() == 1
        assert db_session.query(Message).count() == 2

    def test_round_trip_preserves_message_properties(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        import_service.restore(dump)

        restored = (
            db_session.query(Message).filter_by(external_message_id="msg_ext_1").one()
        )
        assert restored.body_text == "synthetic inbound body"
        assert restored.direction == "in"
        assert restored.remote_visibility == "visible"
        assert restored.thread_external_id == "thread_1"
        assert restored.sent_at == BASE_TIME

    def test_conversation_relationships_are_rebuilt(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        import_service.restore(dump)

        conversation = db_session.query(Conversation).one()
        assert conversation.counterpart_account.external_username == "counterpart_one"
        assert conversation.identity.external_username == "test_identity"
        assert len(conversation.messages) == 2

    def test_message_ordering_within_thread_is_preserved(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        import_service.restore(dump)

        conversation = db_session.query(Conversation).one()
        ordered = sorted(conversation.messages, key=lambda m: m.sent_at)
        assert [m.direction for m in ordered] == ["in", "out"]

    def test_list_membership_is_restored(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        import_service.restore(dump)

        member = db_session.query(ConversationListMember).one()
        assert member.conversation_list.name == "Synthetic List"

    def test_import_into_populated_inbox_skips_duplicates(
        self, db_session, export_service, import_service, seeded
    ):
        dump = export_service.build_dump()

        # Nothing was cleared; every row already exists.
        result = import_service.restore(dump)

        assert result["conversations"]["created"] == 0
        assert result["conversations"]["skipped"] == 1
        assert result["messages"]["created"] == 0
        assert result["messages"]["skipped"] == 2
        assert db_session.query(Message).count() == 2

    def test_importing_twice_is_idempotent(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)

        import_service.restore(dump)
        import_service.restore(dump)

        assert db_session.query(Message).count() == 2
        assert db_session.query(Conversation).count() == 1

    def test_missing_attachment_file_reported_but_message_restored(
        self, db_session, export_service, import_service, clear_service, seeded, attachments_dir
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)
        (attachments_dir / "present.png").unlink()

        result = import_service.restore(dump)

        assert result["warnings"]["missing_files"] == ["present.png"]
        # Messages are still restored despite the missing file.
        assert db_session.query(Message).count() == 2
        assert db_session.query(Attachment).count() == 1

    def test_unknown_counterpart_raises_and_rolls_back(
        self, db_session, import_service, seeded
    ):
        dump = {
            "format": DUMP_FORMAT,
            "version": DUMP_VERSION,
            "identities": [],
            "external_accounts": [],
            "conversations": [
                {
                    "provider_id": "testprov",
                    "external_conversation_id": "conv_unknown",
                    "counterpart_username": "never_seen",
                    "identity_username": "never_seen_either",
                }
            ],
            "messages": [],
            "attachments": [],
        }

        before = db_session.query(Conversation).count()
        with pytest.raises(InvalidDumpError, match="unknown"):
            import_service.restore(dump)

        assert db_session.query(Conversation).count() == before

    def test_failed_import_rolls_back_partial_work(
        self, db_session, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)

        # A second conversation that cannot resolve its counterpart; the first
        # one is valid, so a non-atomic import would leave it behind.
        dump["conversations"].append(
            {
                "provider_id": "testprov",
                "external_conversation_id": "conv_broken",
                "counterpart_username": "does_not_exist",
                "identity_username": "test_identity",
            }
        )

        with pytest.raises(InvalidDumpError):
            import_service.restore(dump)

        assert db_session.query(Conversation).count() == 0
        assert db_session.query(Message).count() == 0

    def test_progress_callback_is_invoked(
        self, export_service, import_service, clear_service, seeded
    ):
        dump = export_service.build_dump()
        clear_service.clear(confirm=True)

        seen = []
        import_service.restore(dump, progress=lambda s, d, t: seen.append(s))

        assert {"conversations", "messages", "attachments"} <= set(seen)


# =============================================================================
# 7.3 Clear
# =============================================================================


class TestClear:
    def test_requires_confirmation(self, db_session, clear_service, seeded):
        with pytest.raises(ValueError, match="confirmation"):
            clear_service.clear(confirm=False)

        assert db_session.query(Message).count() == 2

    def test_removes_inbox_content(self, db_session, clear_service, seeded):
        result = clear_service.clear(confirm=True)

        assert result["conversations"] == 1
        assert result["messages"] == 2
        assert result["attachments"] == 1
        assert db_session.query(Conversation).count() == 0
        assert db_session.query(Message).count() == 0
        assert db_session.query(Attachment).count() == 0
        assert db_session.query(ConversationListMember).count() == 0

    def test_preserves_system_configuration(self, db_session, clear_service, seeded):
        clear_service.clear(confirm=True)

        assert db_session.query(Provider).count() == 1
        assert db_session.query(Identity).count() == 1
        # Accounts survive: leads and profile data reference them.
        assert db_session.query(ExternalAccount).count() == 1
        # List definitions survive so labels are not lost.
        assert db_session.query(ConversationList).count() == 1

    def test_leaves_attachment_files_on_disk(
        self, clear_service, seeded, attachments_dir
    ):
        clear_service.clear(confirm=True)

        # Files must survive so a dump taken earlier can be restored.
        assert (attachments_dir / "present.png").is_file()

    def test_writes_audit_log_entry(self, db_session, clear_service, seeded):
        clear_service.clear(confirm=True)

        entry = db_session.query(AuditLog).filter_by(action_type="inbox.clear").one()
        assert entry.result == "ok"
        assert entry.actor == "user"
        assert entry.response_json["messages"] == 2

    def test_detaches_attachments_referenced_by_profile_items(
        self, db_session, clear_service, seeded
    ):
        # A profile item pointing at the same attachment must not be orphaned.
        profile_item = ProfileItem(
            account_id=seeded["account"].id,
            item_type="image",
            external_item_id="item_1",
            attachment_id=seeded["attachment"].id,
        )
        db_session.add(profile_item)
        db_session.commit()

        result = clear_service.clear(confirm=True)

        assert result["attachments_detached"] == 1
        assert result["attachments"] == 0
        surviving = db_session.query(Attachment).one()
        assert surviving.message_id is None
        assert db_session.query(ProfileItem).count() == 1

    def test_clear_on_empty_inbox_is_a_no_op(self, db_session, clear_service):
        result = clear_service.clear(confirm=True)

        assert result["messages"] == 0
        assert result["conversations"] == 0
