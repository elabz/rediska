"""Contact ban list: service, API, and refusal on every outreach path.

Synthetic `test_` users only. One test per outreach path asserts refusal for a
banned username (the spec drift that left do_not_contact hollow must not recur).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rediska_core.api.deps import get_current_user
from rediska_core.domain.models import (
    AuditLog,
    Conversation,
    DoNotContact,
    ExternalAccount,
    Identity,
    Job,
    LeadPost,
    LocalUser,
    Message,
    Provider,
    ProviderCredential,
    ScoutWatch,
    ScoutWatchPost,
)
from rediska_core.domain.services.ban_list import (
    COUNTERPART_BANNED,
    BanListService,
    BanValidationError,
    CounterpartBannedError,
    banned_usernames,
    is_banned,
)

BANNED = "test_banned_user"


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def world(db_session, test_settings):
    """Provider, identity, credentials, a counterpart and a conversation."""
    from rediska_core.infrastructure.crypto import CryptoService

    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    identity = Identity(
        provider_id="reddit",
        external_username="test_me",
        external_user_id="t2_me",
        display_name="Me",
        is_default=True,
        is_active=True,
    )
    db_session.add(identity)
    db_session.flush()
    counterpart = ExternalAccount(
        provider_id="reddit",
        external_username="Test_Banned_User",  # mixed case on purpose
        external_user_id="t2_other",
        remote_status="active",
    )
    db_session.add(counterpart)
    db_session.flush()
    conversation = Conversation(
        provider_id="reddit",
        identity_id=identity.id,
        counterpart_account_id=counterpart.id,
        external_conversation_id="test_conv_1",
    )
    db_session.add(conversation)
    crypto = CryptoService(test_settings.encryption_key)
    db_session.add(
        ProviderCredential(
            provider_id="reddit",
            identity_id=identity.id,
            credential_type="oauth",
            secret_encrypted=crypto.encrypt('{"access_token": "t", "refresh_token": "t"}'),
        )
    )
    db_session.commit()
    return {"identity": identity, "counterpart": counterpart, "conversation": conversation}


def _lead(db_session, account, ext_id, status="saved"):
    lead = LeadPost(
        provider_id="reddit",
        source_location="r/test_bans",
        external_post_id=ext_id,
        post_url=f"https://reddit.com/comments/{ext_id}",
        author_account_id=account.id,
        status=status,
        lead_source="manual",
        remote_visibility="unknown",
    )
    db_session.add(lead)
    db_session.commit()
    return lead


@pytest.fixture
async def api(test_app, db_session):
    user = MagicMock(spec=LocalUser)
    user.id = 1
    user.username = "test_admin"
    test_app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac
    test_app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def celery_sends():
    sends = []

    def fake_send_task(self, name, **kwargs):
        sends.append((name, kwargs))
        return MagicMock(id="fake")

    with patch("celery.Celery.send_task", new=fake_send_task):
        yield sends


def _ban(db_session, username=BANNED, reason="scam"):
    result = BanListService(db_session).ban("reddit", username, reason)
    db_session.commit()
    return result.entry


# =============================================================================
# SERVICE
# =============================================================================


class TestBanService:
    def test_manual_ban_is_lowercased_active_and_audited(self, db_session, world):
        entry = _ban(db_session, "Some_Test_User")
        assert entry.external_username == "some_test_user"
        assert entry.status == "active" and entry.source == "manual"
        assert is_banned(db_session, "reddit", "SOME_TEST_USER")
        assert is_banned(db_session, "reddit", "u/some_test_user")
        audit = db_session.query(AuditLog).filter_by(action_type="ban.create").one()
        assert audit.entity_id == entry.id

    def test_reason_is_required(self, db_session, world):
        with pytest.raises(BanValidationError):
            BanListService(db_session).ban("reddit", BANNED, "  ")

    def test_banning_twice_is_idempotent(self, db_session, world):
        _ban(db_session)
        again = BanListService(db_session).ban("reddit", BANNED.upper(), "scam")
        assert not again.created and not again.reactivated
        assert db_session.query(DoNotContact).count() == 1
        assert db_session.query(AuditLog).filter_by(action_type="ban.create").count() == 1

    def test_lift_keeps_history_and_reban_reactivates_same_row(self, db_session, world):
        entry = _ban(db_session)
        service = BanListService(db_session)
        service.lift(entry.id)
        db_session.commit()
        assert entry.status == "lifted" and entry.lifted_at is not None
        assert not is_banned(db_session, "reddit", BANNED)

        result = service.ban("reddit", BANNED, "hostile", notes="came back")
        db_session.commit()
        assert result.reactivated and result.entry.id == entry.id
        assert entry.status == "active" and entry.lifted_at is None
        assert "Re-banned" in (entry.notes or "")
        assert db_session.query(DoNotContact).count() == 1
        assert db_session.query(AuditLog).filter_by(action_type="ban.lift").count() == 1

    def test_ban_withdraws_active_leads_and_lift_restores_them(self, db_session, world):
        account = world["counterpart"]
        saved = _lead(db_session, account, "test_l1", "saved")
        new = _lead(db_session, account, "test_l2", "new")
        contacted = _lead(db_session, account, "test_l3", "contacted")

        entry = _ban(db_session)
        db_session.refresh(saved)
        db_session.refresh(new)
        db_session.refresh(contacted)
        assert saved.status == "ignored" and saved.status_before_ban == "saved"
        assert new.status == "ignored" and new.status_before_ban == "new"
        assert contacted.status == "contacted" and contacted.status_before_ban is None

        _, restored = BanListService(db_session).lift(entry.id)
        db_session.commit()
        db_session.refresh(saved)
        db_session.refresh(new)
        assert set(restored) == {saved.id, new.id}
        assert saved.status == "saved" and saved.status_before_ban is None
        assert new.status == "new"

    def test_lift_does_not_override_a_status_the_user_changed(self, db_session, world):
        lead = _lead(db_session, world["counterpart"], "test_l4", "saved")
        entry = _ban(db_session)
        lead.status = "contacted"
        db_session.commit()
        BanListService(db_session).lift(entry.id)
        db_session.commit()
        db_session.refresh(lead)
        assert lead.status == "contacted" and lead.status_before_ban is None

    def test_bulk_ban_with_exclusion_is_one_audited_batch(self, db_session, world):
        names = ["test_r1", "test_r2", "test_r3", "test_r4", "test_r5"]
        results = BanListService(db_session).bulk_ban(
            "reddit", names, "copy_ring", cluster_id=42, exclude_usernames=["TEST_R1"]
        )
        db_session.commit()
        assert sorted(r.entry.external_username for r in results) == names[1:]
        assert all(r.entry.source == "copy_ring" and r.entry.cluster_id == 42 for r in results)
        assert db_session.query(AuditLog).filter_by(action_type="ban.create").count() == 0
        bulk = db_session.query(AuditLog).filter_by(action_type="ban.bulk_create").one()
        assert len(bulk.response_json["banned"]) == 4
        assert banned_usernames(db_session, "reddit") == set(names[1:])

    def test_suggestions_empty_without_copy_tables(self, db_session, world):
        assert BanListService(db_session).suggestions() == []


# =============================================================================
# READERS: scout skip + source discovery
# =============================================================================


class TestReaders:
    def test_scout_verdict_skips_banned_author_case_insensitively(self, db_session, world):
        from rediska_core.domain.services.scout_watch import (
            SKIP_DO_NOT_CONTACT,
            ScoutWatchService,
        )

        entry = _ban(db_session)
        service = ScoutWatchService(db_session)
        assert service.check_author_verdict("reddit", "TEST_BANNED_USER") == SKIP_DO_NOT_CONTACT
        BanListService(db_session).lift(entry.id)
        db_session.commit()
        assert service.check_author_verdict("reddit", "TEST_BANNED_USER") != SKIP_DO_NOT_CONTACT


# =============================================================================
# OUTREACH PATHS
# =============================================================================


class TestOutreachRefusal:
    @pytest.mark.asyncio
    async def test_send_in_existing_conversation_is_refused(
        self, api, db_session, world, celery_sends
    ):
        _ban(db_session)
        resp = await api.post(
            f"/conversations/{world['conversation'].id}/messages", json={"body_text": "hi"}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == COUNTERPART_BANNED
        assert db_session.query(Message).count() == 0
        assert celery_sends == []

    @pytest.mark.asyncio
    async def test_lifted_ban_does_not_block_send(self, api, db_session, world, celery_sends):
        entry = _ban(db_session)
        BanListService(db_session).lift(entry.id)
        db_session.commit()
        resp = await api.post(
            f"/conversations/{world['conversation'].id}/messages", json={"body_text": "hi"}
        )
        assert resp.status_code == 202
        assert len(celery_sends) == 1

    @pytest.mark.asyncio
    async def test_retry_of_pending_message_is_refused(
        self, api, db_session, world, celery_sends
    ):
        msg = Message(
            provider_id="reddit",
            identity_id=world["identity"].id,
            conversation_id=world["conversation"].id,
            direction="out",
            sent_at=datetime.utcnow(),
            body_text="queued before the ban",
            remote_visibility="send_failed",
        )
        db_session.add(msg)
        db_session.commit()
        _ban(db_session)

        resp = await api.post(
            f"/conversations/{world['conversation'].id}/messages/{msg.id}/retry"
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == COUNTERPART_BANNED
        db_session.refresh(msg)
        assert msg.remote_visibility == "send_failed"
        assert celery_sends == []

    @pytest.mark.asyncio
    async def test_initiate_by_username_is_refused_before_any_row(
        self, api, db_session, world
    ):
        _ban(db_session, "test_stranger")
        resp = await api.post(
            "/conversations/initiate/by-username",
            json={"username": "Test_Stranger", "provider_id": "reddit"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == COUNTERPART_BANNED
        assert (
            db_session.query(ExternalAccount)
            .filter(ExternalAccount.external_username.ilike("test_stranger"))
            .count()
            == 0
        )

    @pytest.mark.asyncio
    async def test_initiate_from_lead_is_refused_with_different_case(
        self, api, db_session, world
    ):
        stranger = ExternalAccount(
            provider_id="reddit", external_username="Test_Lead_Author", remote_status="active"
        )
        db_session.add(stranger)
        db_session.commit()
        lead = _lead(db_session, stranger, "test_l9", "saved")
        _ban(db_session, "TEST_LEAD_AUTHOR")

        resp = await api.post(f"/conversations/initiate/from-lead/{lead.id}")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == COUNTERPART_BANNED
        assert (
            db_session.query(Conversation)
            .filter(Conversation.counterpart_account_id == stranger.id)
            .count()
            == 0
        )

    def test_validate_send_raises(self, db_session, world):
        from rediska_core.domain.services.send_message import SendMessageService

        _ban(db_session)
        with pytest.raises(CounterpartBannedError):
            SendMessageService(db_session).validate_send(world["conversation"].id, "hi")

    def test_queued_then_banned_makes_no_provider_call(
        self, db_session, sync_session_factory, world, test_settings
    ):
        """The worker re-checks immediately before the provider call."""
        from rediska_core.domain.services.send_message import SendMessageService

        result = SendMessageService(db_session).enqueue_send(world["conversation"].id, "hi")
        db_session.commit()
        job = db_session.get(Job, result.job_id)
        payload = dict(job.payload_json)

        _ban(db_session)  # lands after the enqueue, before the worker runs

        from rediska_worker.tasks import message as message_task

        adapter = MagicMock()
        with (
            patch("rediska_core.config.get_settings", return_value=test_settings),
            patch(
                "rediska_core.infra.db.get_sync_session_factory",
                return_value=sync_session_factory,
            ),
            patch(
                "rediska_core.domain.services.credentials.CredentialsService.get_credential_decrypted",
                return_value='{"access_token": "t", "refresh_token": "t"}',
            ),
            patch("rediska_core.providers.reddit.adapter.RedditAdapter", return_value=adapter),
        ):
            out = message_task.send_manual.run(payload)

        assert out["status"] == "refused" and out["error"] == COUNTERPART_BANNED
        adapter.send_message.assert_not_called()
        db_session.expire_all()
        msg = db_session.get(Message, result.message_id)
        assert msg.remote_visibility == "send_failed"
        assert msg.send_error == COUNTERPART_BANNED


# =============================================================================
# API + QUEUES
# =============================================================================


class TestBanApi:
    @pytest.mark.asyncio
    async def test_create_list_status_lift(self, api, db_session, world):
        lead = _lead(db_session, world["counterpart"], "test_l5", "saved")

        resp = await api.post(
            "/ban-list", json={"username": "Test_Banned_User", "reason": "scam", "notes": "n"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] and body["leads_withdrawn"] == [lead.id]
        ban_id = body["entry"]["id"]
        assert body["entry"]["account_id"] == world["counterpart"].id

        listing = (await api.get("/ban-list", params={"q": "banned"})).json()
        assert [e["id"] for e in listing["items"]] == [ban_id]
        assert listing["items"][0]["lead_ids"] == [lead.id]
        assert (await api.get("/ban-list", params={"status": "lifted"})).json()["items"] == []

        status = (await api.get("/ban-list/status", params={"username": "TEST_BANNED_USER"})).json()
        assert status["banned"] is True

        lifted = await api.post(f"/ban-list/{ban_id}/lift", json={"notes": "mistake"})
        assert lifted.status_code == 200
        assert lifted.json()["entry"]["status"] == "lifted"
        assert lifted.json()["leads_restored"] == [lead.id]
        status = (await api.get("/ban-list/status", params={"username": BANNED})).json()
        assert status["banned"] is False and status["entry"]["status"] == "lifted"

    @pytest.mark.asyncio
    async def test_lift_missing_is_404(self, api, world):
        assert (await api.post("/ban-list/999/lift")).status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_by_usernames(self, api, db_session, world):
        resp = await api.post(
            "/ban-list/bulk",
            json={
                "usernames": ["test_a", "test_b", "test_c"],
                "reason": "copy_ring",
                "exclude_usernames": ["test_a"],
            },
        )
        assert resp.status_code == 200
        assert sorted(b["entry"]["username"] for b in resp.json()["banned"]) == ["test_b", "test_c"]

    @pytest.mark.asyncio
    async def test_suggestions_and_cluster_bulk_ban(self, api, db_session, world):
        from rediska_core.domain.services.post_copy import fingerprint_post

        body = (await api.get("/ban-list/suggestions")).json()
        assert body == {"available": True, "items": []}

        text = " ".join(f"w{i}" for i in range(300))
        cluster_id = None
        for i, name in enumerate(("test_ring_a", "test_ring_b")):
            out = fingerprint_post(
                db_session, provider_id="reddit", external_post_id=f"ring{i}",
                author_username=name, body_text=text, source="scout",
            )
            cluster_id = out.cluster_id or cluster_id
        db_session.commit()

        items = (await api.get("/ban-list/suggestions")).json()["items"]
        assert [i["cluster_id"] for i in items] == [cluster_id]
        resp = await api.post(
            "/ban-list/bulk", json={"cluster_id": cluster_id, "reason": "copy_ring"}
        )
        assert resp.status_code == 200
        assert sorted(b["entry"]["username"] for b in resp.json()["banned"]) == [
            "test_ring_a", "test_ring_b",
        ]
        assert (await api.get("/ban-list/suggestions")).json()["items"] == []

    @pytest.mark.asyncio
    async def test_leads_list_hides_banned_unless_asked(self, api, db_session, world):
        other = ExternalAccount(
            provider_id="reddit", external_username="test_fine", remote_status="active"
        )
        db_session.add(other)
        db_session.commit()
        banned_lead = _lead(db_session, world["counterpart"], "test_l6", "contacted")
        fine_lead = _lead(db_session, other, "test_l7", "contacted")
        _ban(db_session)

        ids = {l["id"] for l in (await api.get("/leads")).json()["leads"]}
        assert fine_lead.id in ids and banned_lead.id not in ids
        ids = {
            l["id"]
            for l in (await api.get("/leads", params={"include_banned": "true"})).json()["leads"]
        }
        assert {fine_lead.id, banned_lead.id} <= ids

    def test_needs_review_hides_banned_unless_asked(self, db_session, world):
        from rediska_core.domain.services.scout_watch import ScoutWatchService

        watch = ScoutWatch(
            provider_id="reddit",
            source_location="r/test_bans",
            search_query="q",
            sort_by="new",
            time_filter="day",
            min_confidence=0.7,
        )
        db_session.add(watch)
        db_session.commit()
        for ext, author in (("test_p1", "Test_Banned_User"), ("test_p2", "test_fine")):
            db_session.add(
                ScoutWatchPost(
                    watch_id=watch.id,
                    external_post_id=ext,
                    post_title="t",
                    post_body="b",
                    post_author=author,
                    first_seen_at=datetime.utcnow(),
                    analysis_status="analyzed",
                    analysis_recommendation="needs_review",
                    analysis_confidence=0.5,
                )
            )
        db_session.commit()
        _ban(db_session)

        service = ScoutWatchService(db_session)
        posts, _ = service.list_needs_review()
        assert [p.post_author for p in posts] == ["test_fine"]
        assert service.count_needs_review() == 1
        posts, _ = service.list_needs_review(include_banned=True)
        assert len(posts) == 2
