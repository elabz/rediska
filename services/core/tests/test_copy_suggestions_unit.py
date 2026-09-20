"""Probable rewrites: suggestions are stored, never acted on by themselves.

Synthetic `test_` data only.
"""

from datetime import datetime, timedelta

import pytest

from rediska_core.domain.models import (
    AuditLog,
    CopyCluster,
    CopyClusterMember,
    CopySuggestion,
    ExternalAccount,
    LeadPost,
    PostFingerprint,
    Provider,
)
from rediska_core.domain.services import copy_suggestions

NOW = datetime(2026, 9, 20, 12, 0, 0)


@pytest.fixture
def world(db_session):
    db_session.add(Provider(provider_id="reddit", display_name="Reddit", enabled=True))
    db_session.flush()
    accounts = {}
    for name in ("test_alice", "test_bob"):
        account = ExternalAccount(provider_id="reddit", external_username=name)
        db_session.add(account)
        accounts[name] = account
    db_session.flush()
    return accounts


def lead(db_session, account, post_id, title="test_title"):
    row = LeadPost(
        provider_id="reddit",
        source_location="test_sub",
        external_post_id=post_id,
        post_url=f"https://example.invalid/{post_id}",
        author_account_id=account.id,
        title=title,
        body_text="test body text",
        status="new",
        remote_visibility="visible",
    )
    db_session.add(row)
    db_session.flush()
    return row


def fingerprint(db_session, post_id, author, when=NOW):
    row = PostFingerprint(
        provider_id="reddit",
        external_post_id=post_id,
        author_username=author,
        posted_at=when,
        first_seen_at=when,
        exact_hash=post_id.encode()[:16].ljust(16, b"\0"),
        source="scout",
        char_len=500,
    )
    db_session.add(row)
    db_session.flush()
    return row


def match_for(row, similarity=0.96, author="test_bob"):
    return {
        "doc_type": "lead_post",
        "entity_id": row.id,
        "similarity": similarity,
        "author_username": author,
    }


class TestRecording:
    def test_a_neighbour_becomes_a_pending_suggestion(self, db_session, world):
        other = lead(db_session, world["test_bob"], "test_post_b")
        counts = copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
            embedding_model="test-embed-model",
        )

        assert counts["created"] == 1
        row = db_session.query(CopySuggestion).one()
        assert row.status == "new"
        assert row.match_external_post_id == "test_post_b"
        assert row.similarity == pytest.approx(0.96)

    def test_the_same_author_is_a_repost_not_a_copy(self, db_session, world):
        other = lead(db_session, world["test_alice"], "test_post_b")
        counts = copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other, author="test_alice")],
        )

        assert counts["created"] == 0
        assert db_session.query(CopySuggestion).count() == 0

    def test_posts_already_in_one_cluster_are_not_suggested(self, db_session, world):
        other = lead(db_session, world["test_bob"], "test_post_b")
        fp_a = fingerprint(db_session, "test_post_a", "test_alice")
        fp_b = fingerprint(db_session, "test_post_b", "test_bob")
        cluster = CopyCluster(
            provider_id="reddit", kind="unclassified", created_at=NOW, updated_at=NOW
        )
        db_session.add(cluster)
        db_session.flush()
        for fp in (fp_a, fp_b):
            db_session.add(
                CopyClusterMember(cluster_id=cluster.id, fingerprint_id=fp.id, joined_at=NOW)
            )
        db_session.flush()

        counts = copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
        )

        assert counts["skipped_clustered"] == 1
        assert db_session.query(CopySuggestion).count() == 0

    def test_a_rejected_pair_is_not_suggested_again(self, db_session, world):
        """Re-embedding a post must not resurrect a decision the user made."""
        other = lead(db_session, world["test_bob"], "test_post_b")
        args = dict(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
        )
        copy_suggestions.record_suggestions(**args)
        row = db_session.query(CopySuggestion).one()
        copy_suggestions.reject(db_session, row.id)

        counts = copy_suggestions.record_suggestions(**args)

        assert counts["skipped_existing"] == 1
        assert db_session.query(CopySuggestion).count() == 1


class TestDecisions:
    def _pending(self, db_session, world):
        lead(db_session, world["test_alice"], "test_post_a")
        other = lead(db_session, world["test_bob"], "test_post_b")
        fingerprint(db_session, "test_post_a", "test_alice")
        fingerprint(db_session, "test_post_b", "test_bob", when=NOW - timedelta(days=2))
        copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
        )
        return db_session.query(CopySuggestion).one()

    def test_accept_clusters_the_two_posts(self, db_session, world):
        row = self._pending(db_session, world)

        accepted = copy_suggestions.accept(db_session, row.id)

        assert accepted.status == "accepted"
        assert accepted.cluster_id is not None
        members = (
            db_session.query(CopyClusterMember)
            .filter_by(cluster_id=accepted.cluster_id)
            .all()
        )
        assert len(members) == 2

    def test_accept_is_audited(self, db_session, world):
        row = self._pending(db_session, world)
        copy_suggestions.accept(db_session, row.id)

        actions = [a.action_type for a in db_session.query(AuditLog).all()]
        assert "copy_suggestion.accept" in actions

    def test_reject_clusters_nothing(self, db_session, world):
        row = self._pending(db_session, world)

        rejected = copy_suggestions.reject(db_session, row.id)

        assert rejected.status == "rejected"
        assert rejected.cluster_id is None
        assert db_session.query(CopyClusterMember).count() == 0
        actions = [a.action_type for a in db_session.query(AuditLog).all()]
        assert "copy_suggestion.reject" in actions

    def test_deciding_twice_is_refused(self, db_session, world):
        row = self._pending(db_session, world)
        copy_suggestions.reject(db_session, row.id)

        with pytest.raises(copy_suggestions.SuggestionAlreadyDecided):
            copy_suggestions.accept(db_session, row.id)

    def test_unknown_suggestion(self, db_session):
        with pytest.raises(copy_suggestions.SuggestionNotFound):
            copy_suggestions.accept(db_session, 4040)


class TestReadModels:
    def test_a_post_sees_its_suggestion_from_either_side(self, db_session, world):
        other = lead(db_session, world["test_bob"], "test_post_b")
        copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
        )

        found = copy_suggestions.suggestions_for_posts(
            db_session, "reddit", ["test_post_a", "test_post_b"]
        )

        assert set(found) == {"test_post_a", "test_post_b"}

    def test_decided_suggestions_leave_the_read_model(self, db_session, world):
        other = lead(db_session, world["test_bob"], "test_post_b")
        copy_suggestions.record_suggestions(
            db=db_session,
            provider_id="reddit",
            doc_type="lead_post",
            entity_id=1,
            external_post_id="test_post_a",
            author_username="test_alice",
            matches=[match_for(other)],
        )
        row = db_session.query(CopySuggestion).one()
        copy_suggestions.reject(db_session, row.id)

        found = copy_suggestions.suggestions_for_posts(
            db_session, "reddit", ["test_post_a"]
        )

        assert found == {}
